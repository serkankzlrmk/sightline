"""
ReliefWeb pgvector Vector Store
Semantic search over ingested report chunks using PostgreSQL + pgvector.

Replaces ChromaDB with a cloud-hosted PostgreSQL database (Supabase)
that has the pgvector extension enabled.

Usage:
    from reliefweb_api.pgvector_store import PgVectorStore

    vs = PgVectorStore()
    results = vs.search("Sudan flooding health", n_results=5, country="Sudan")
"""

import os
import json
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2 import sql, extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import numpy as np
except ImportError:
    np = None

from config import (
    SUPABASE_DB_URL,
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    EMBEDDING_DIM,
    RETRIEVAL_TOP_K,
    RETRIEVAL_TOP_K_SUMMARY,
)


# ============================================================================
# CONFIGURATION
# ============================================================================

# Supabase connection string (PostgreSQL)
# Format: postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
DB_URL: str = os.getenv("SUPABASE_DB_URL", SUPABASE_DB_URL)
# Supabase REST API config (fallback when direct DB connection is unavailable)
SUPABASE_REST_URL: str = os.getenv("SUPABASE_URL", SUPABASE_URL)
SUPABASE_REST_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", SUPABASE_SERVICE_KEY)
# EMBEDDING_DIM imported from config.py — do not redeclare here


# ============================================================================
# EMBEDDING FUNCTION
# ============================================================================

def get_embedding_function():
    """Return the embedding function compatible with ChromaDB's DefaultEmbeddingFunction."""
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        return DefaultEmbeddingFunction()
    except ImportError:
        raise ImportError(
            "chromadb is required for embeddings. Install it with: pip install chromadb"
        )


def _parse_embedding(emb):
    """Parse an embedding value from pgvector into a Python list of floats.

    psycopg2 may return pgvector columns as:
      - str:  '[-0.07,0.05,...]'  (most common with text connection)
      - list: [−0.07, 0.05, ...]  (if using register_vector adapter)
      - np.ndarray: array([...])   (if numpy adapter is registered)

    This function normalises all formats to a plain Python list of floats.
    """
    if emb is None:
        return None
    # Already a list of floats — return as-is
    if isinstance(emb, list):
        return emb
    # numpy ndarray — convert to list
    if np is not None and isinstance(emb, np.ndarray):
        return emb.tolist()
    # String like '[-0.07,0.05,...]' — parse it
    if isinstance(emb, str):
        import json as _json
        try:
            parsed = _json.loads(emb)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback: strip brackets and split by comma
        stripped = emb.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            stripped = stripped[1:-1]
        return [float(x) for x in stripped.split(',') if x.strip()]
    # Unknown type — try numpy conversion as last resort
    if np is not None:
        try:
            return np.array(emb).tolist()
        except Exception:
            pass
    return None


# ============================================================================
# PGVECTOR VECTOR STORE
# ============================================================================

class PgVectorStore:
    """
    PostgreSQL + pgvector-backed semantic search over ReliefWeb report chunks.

    Uses Supabase's PostgreSQL database with the pgvector extension for
    vector similarity search (cosine distance).

    Tables:
      reports  - full metadata, one row per report (unique on report_id)
      chunks  - text fragments with metadata, plus embedding vector column

    Chunk IDs: "{report_id}_{chunk_index}"
    """

    def __init__(self, db_url: str = DB_URL):
        self.db_url = db_url
        self.conn = None
        self.ef = get_embedding_function()
        self._use_rest = False  # Fallback to REST API if DB connection fails
        self._ensure_connection()

    def _ensure_connection(self):
        """Ensure we have a live database connection. Falls back to REST API if unavailable."""
        if not HAS_PSYCOPG2:
            self._use_rest = True
            return
        try:
            if self.conn is None or self.conn.closed:
                self.conn = psycopg2.connect(self.db_url)
                self.conn.autocommit = True
        except Exception as e:
            # Direct DB connection failed — use REST API fallback
            logger.warning(f"Direct DB connection failed, falling back to REST API: {e}")
            self._use_rest = True
            self.conn = None

    def _get_cursor(self):
        """Get a fresh cursor, reconnecting if needed."""
        if self._use_rest:
            raise RuntimeError("Using REST API fallback — direct DB cursor not available")
        self._ensure_connection()
        return self.conn.cursor()

    def _rest_headers(self, service: bool = True) -> dict:
        """Get headers for Supabase REST API."""
        key = SUPABASE_REST_KEY if service else os.getenv("SUPABASE_ANON_KEY", "")
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _rest_get(self, path: str, params: dict = None) -> dict:
        """GET request to Supabase REST API."""
        resp = requests.get(
            f"{SUPABASE_REST_URL}/rest/v1/{path}",
            headers=self._rest_headers(),
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _rest_post(self, path: str, data, params: dict = None) -> dict:
        """POST request to Supabase REST API."""
        headers = self._rest_headers()
        headers["Prefer"] = "return=minimal"
        resp = requests.post(
            f"{SUPABASE_REST_URL}/rest/v1/{path}",
            json=data,
            headers=headers,
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def _rest_rpc(self, func: str, params: dict = None) -> dict:
        """RPC call to Supabase SQL function."""
        resp = requests.post(
            f"{SUPABASE_REST_URL}/rest/v1/rpc/{func}",
            json=params or {},
            headers=self._rest_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # -------------------------------------------------------------------------
    # SCHEMA SETUP
    # -------------------------------------------------------------------------

    def ensure_schema(self):
        """Create tables and indexes if they don't exist."""
        cur = self._get_cursor()
        try:
            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Reports table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    report_id INTEGER PRIMARY KEY,
                    title TEXT DEFAULT '',
                    date DATE,
                    source TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    countries JSONB DEFAULT '[]'::jsonb,
                    themes JSONB DEFAULT '[]'::jsonb,
                    format_type TEXT DEFAULT '',
                    language TEXT DEFAULT '',
                    has_pdf BOOLEAN DEFAULT FALSE,
                    has_content BOOLEAN DEFAULT FALSE,
                    pdf_pages INTEGER DEFAULT 0,
                    total_chunks INTEGER DEFAULT 0,
                    ingested_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # Chunks table with embedding column
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    id SERIAL PRIMARY KEY,
                    report_id INTEGER REFERENCES reports(report_id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    source_type TEXT DEFAULT 'html',
                    content TEXT NOT NULL,
                    char_count INTEGER DEFAULT 0,
                    embedding vector({EMBEDDING_DIM}),
                    title TEXT DEFAULT '',
                    date TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    primary_country TEXT DEFAULT '',
                    all_countries TEXT DEFAULT '',
                    themes TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    UNIQUE(report_id, chunk_index)
                );
            """)

            # Indexes for fast lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_report_id ON chunks(report_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_primary_country ON chunks(primary_country);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_date ON chunks(date);
            """)

            # HNSW index for vector similarity (cosine distance)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
                USING hnsw (embedding vector_cosine_ops);
            """)

            # Index for JSONB country queries
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_reports_countries ON reports USING gin (countries);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_reports_themes ON reports USING gin (themes);
            """)

            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise e
        finally:
            cur.close()

    # -------------------------------------------------------------------------
    # DEDUPLICATION
    # -------------------------------------------------------------------------

    def report_exists(self, report_id: int) -> bool:
        """Fast check: does this report exist in the database?"""
        cur = self._get_cursor()
        try:
            cur.execute(
                "SELECT 1 FROM chunks WHERE report_id = %s AND chunk_index = 0 LIMIT 1",
                (report_id,)
            )
            return cur.fetchone() is not None
        finally:
            cur.close()

    # -------------------------------------------------------------------------
    # INSERT
    # -------------------------------------------------------------------------

    def add_report(
        self,
        report_id: int,
        chunks: List[Dict],
        report_meta: Dict,
    ) -> int:
        """
        Embed and add all chunks for one report.

        Args:
            report_id: Integer report ID
            chunks: List of {"source_type": "pdf"|"html", "content": str}
            report_meta: Parsed metadata.json dict (used for metadata fields)

        Returns:
            Number of chunks added.
        """
        if not chunks:
            return 0

        # ---- flatten metadata ----
        sources = report_meta.get("source", [])
        source_name = sources[0].get("shortname", "") if sources else ""

        date_obj = report_meta.get("date", {})
        date_str = (
            date_obj.get("original", date_obj.get("created", ""))
            if isinstance(date_obj, dict) else str(date_obj)
        )[:10]

        countries = report_meta.get("countries", [])
        # Handle both dict and string entries in countries list
        def _get_country_name(c):
            if isinstance(c, dict):
                return c.get("shortname", c.get("name", ""))
            return str(c) if c else ""

        primary_country = _get_country_name(countries[0]) if countries else ""
        all_countries = ", ".join(_get_country_name(c) for c in countries[:8])
        themes = [t.get("name", "") for t in report_meta.get("themes", [])]
        themes_str = ", ".join(themes[:6])

        # format/language are lists of dicts from ReliefWeb API
        raw_format = report_meta.get("format", [])
        format_name = raw_format[0].get("name", "") if isinstance(raw_format, list) and raw_format else (raw_format.get("name", "") if isinstance(raw_format, dict) else str(raw_format) if raw_format else "")
        raw_language = report_meta.get("language", [])
        language_name = raw_language[0].get("name", "") if isinstance(raw_language, list) and raw_language else (raw_language.get("name", "") if isinstance(raw_language, dict) else str(raw_language) if raw_language else "")

        # ---- compute embeddings ----
        documents = [c["content"] for c in chunks]
        embeddings = self.ef(documents)

        # ---- insert report metadata (upsert to satisfy FK) ----
        cur = self._get_cursor()
        try:
            cur.execute(
                """
                INSERT INTO reports (report_id, title, date, source, url, countries, themes,
                                      format_type, language, total_chunks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (report_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    date = EXCLUDED.date,
                    source = EXCLUDED.source,
                    url = EXCLUDED.url,
                    countries = EXCLUDED.countries,
                    themes = EXCLUDED.themes,
                    total_chunks = EXCLUDED.total_chunks
                """,
                (
                    report_id,
                    report_meta.get("title", ""),
                    date_str or None,
                    source_name,
                    report_meta.get("url", ""),
                    json.dumps(countries, ensure_ascii=False) if countries else "[]",
                    json.dumps(themes, ensure_ascii=False) if themes else "[]",
                    format_name,
                    language_name,
                    len(chunks),
                ),
            )

            # ---- insert chunks ----
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
                cur.execute(
                    """
                    INSERT INTO chunks
                        (report_id, chunk_index, source_type, content, char_count,
                         embedding, title, date, source, primary_country,
                         all_countries, themes, url)
                    VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (report_id, chunk_index) DO NOTHING
                    """,
                    (
                        report_id,
                        i,
                        chunk["source_type"],
                        chunk["content"],
                        len(chunk["content"]),
                        emb_str,
                        report_meta.get("title", ""),
                        date_str,
                        source_name,
                        primary_country,
                        all_countries,
                        themes_str,
                        report_meta.get("url", ""),
                    ),
                )
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise e
        finally:
            cur.close()

        return len(chunks)

    # -------------------------------------------------------------------------
    # SEARCH
    # -------------------------------------------------------------------------

    def search(
        self,
        query: str,
        n_results: int = RETRIEVAL_TOP_K,
        country: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[Dict]:
        """
        Semantic search over all ingested chunks using pgvector.

        Args:
            query: Natural language search query
            n_results: Max chunks to return
            country: Filter by primary_country (exact match)
            source: Filter by source org shortname

        Returns:
            List of dicts with rank, similarity, report_id, title, date,
            source, countries, source_type, url, chunk_preview
        """
        # Compute query embedding
        query_embedding = self.ef([query])[0]
        emb_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        # Build WHERE clause
        conditions = []
        params = [emb_str, n_results]
        param_idx = 3

        if country:
            conditions.append(f"primary_country = %s")
            params.append(country)
            param_idx += 1

        if source:
            conditions.append(f"source = %s")
            params.append(source)
            param_idx += 1

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Build final params: [query_emb, ...filters..., query_emb, limit]
        final_params = [emb_str]
        if country:
            final_params.append(country)
        if source:
            final_params.append(source)
        final_params.append(emb_str)
        final_params.append(n_results)

        query_sql = f"""
            SELECT
                report_id, chunk_index, source_type, content,
                title, date, source, primary_country, all_countries, themes, url,
                1 - (embedding <=> %s::vector) AS similarity
            FROM chunks
            {where_clause}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """

        cur = self._get_cursor()
        try:
            cur.execute(query_sql, final_params)
            rows = cur.fetchall()
        finally:
            cur.close()

        output = []
        for rank, row in enumerate(rows, start=1):
            (
                report_id, chunk_index, source_type, content,
                title, date, source, primary_country, all_countries, themes, url,
                similarity
            ) = row
            output.append({
                "rank": rank,
                "similarity": round(float(similarity), 3),
                "report_id": report_id,
                "title": title,
                "date": date,
                "source": source,
                "countries": all_countries,
                "source_type": source_type,
                "url": url,
                "chunk_preview": (content or "")[:400],
            })

        return output

    # -------------------------------------------------------------------------
    # STATS
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Return database statistics."""
        if self._use_rest:
            headers = self._rest_headers()
            headers["Prefer"] = "count=exact"
            r_resp = requests.get(
                f"{SUPABASE_REST_URL}/rest/v1/reports?select=report_id&limit=0",
                headers=headers, timeout=10,
            )
            c_resp = requests.get(
                f"{SUPABASE_REST_URL}/rest/v1/chunks?select=id&limit=0",
                headers=headers, timeout=10,
            )
            report_count = int(r_resp.headers.get("content-range", "*/0").split("/")[-1]) if r_resp.status_code == 200 else 0
            chunk_count = int(c_resp.headers.get("content-range", "*/0").split("/")[-1]) if c_resp.status_code == 200 else 0
            return {
                "total_chunks": chunk_count,
                "total_reports": report_count,
                "backend": "pgvector",
                "embedding_dim": EMBEDDING_DIM,
            }
        cur = self._get_cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM chunks;")
            chunk_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM reports;")
            report_count = cur.fetchone()[0]
            return {
                "total_chunks": chunk_count,
                "total_reports": report_count,
                "backend": "pgvector",
                "embedding_dim": EMBEDDING_DIM,
            }
        finally:
            cur.close()

    def count(self) -> int:
        """Total chunk count."""
        if self._use_rest:
            headers = self._rest_headers()
            headers["Prefer"] = "count=exact"
            resp = requests.get(
                f"{SUPABASE_REST_URL}/rest/v1/chunks?select=id&limit=0",
                headers=headers, timeout=10,
            )
            return int(resp.headers.get("content-range", "*/0").split("/")[-1]) if resp.status_code == 200 else 0
        cur = self._get_cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM chunks;")
            return cur.fetchone()[0]
        finally:
            cur.close()

    # -------------------------------------------------------------------------
    # PURGE
    # -------------------------------------------------------------------------

    def purge_by_report_ids(self, report_ids: List[int]) -> int:
        """Remove all chunks belonging to the given report_ids.
        Reports are also deleted via CASCADE.

        Returns the number of chunks removed.
        """
        if not report_ids:
            return 0

        cur = self._get_cursor()
        try:
            # Count chunks to be removed
            cur.execute(
                "SELECT COUNT(*) FROM chunks WHERE report_id = ANY(%s)",
                (report_ids,)
            )
            count = cur.fetchone()[0]

            # Delete reports (cascades to chunks)
            cur.execute(
                "DELETE FROM reports WHERE report_id = ANY(%s)",
                (report_ids,)
            )
            self.conn.commit()
            return count
        except Exception as e:
            self.conn.rollback()
            raise e
        finally:
            cur.close()

    # -------------------------------------------------------------------------
    # LIST COUNTRIES / THEMES (for SITREP)
    # -------------------------------------------------------------------------

    def list_countries(self) -> List[str]:
        """Get unique primary_country values from chunks."""
        if self._use_rest:
            result = self._rest_rpc("list_countries")
            return [r["country"] for r in result]
        cur = self._get_cursor()
        try:
            cur.execute("""
                SELECT DISTINCT primary_country FROM chunks
                WHERE primary_country IS NOT NULL AND primary_country != ''
                ORDER BY primary_country;
            """)
            return [row[0] for row in cur.fetchall()]
        finally:
            cur.close()

    def list_countries_with_counts(self) -> List[Dict]:
        """Get countries with chunk counts, ordered by count descending."""
        if self._use_rest:
            result = self._rest_rpc("list_countries_with_counts")
            return result  # Already in [{name, count}] format
        cur = self._get_cursor()
        try:
            cur.execute("""
                SELECT primary_country, COUNT(*) as cnt
                FROM chunks
                WHERE primary_country IS NOT NULL AND primary_country != ''
                GROUP BY primary_country
                ORDER BY cnt DESC;
            """)
            return [{"name": row[0], "count": row[1]} for row in cur.fetchall()]
        finally:
            cur.close()

    def list_themes(self) -> List[str]:
        """Get unique themes from chunks (comma-separated field)."""
        if self._use_rest:
            result = self._rest_rpc("list_themes")
            return [r["theme"] for r in result]
        cur = self._get_cursor()
        try:
            cur.execute("""
                SELECT DISTINCT themes FROM chunks
                WHERE themes IS NOT NULL AND themes != '';
            """)
            themes_set = set()
            for row in cur.fetchall():
                if row[0]:
                    for t in row[0].split(","):
                        t = t.strip()
                        if t:
                            themes_set.add(t)
            return sorted(themes_set)
        finally:
            cur.close()

    def get_date_range(self, country: str) -> Dict:
        """Get min/max date for chunks matching a country."""
        if self._use_rest:
            result = self._rest_rpc("get_date_range", {"country_name": country})
            if result and isinstance(result, list) and len(result) > 0:
                return {"min": result[0].get("min_date"), "max": result[0].get("max_date"), "count": result[0].get("count", 0)}
            return {"min": None, "max": None, "count": 0}
        cur = self._get_cursor()
        try:
            cur.execute("""
                SELECT MIN(date), MAX(date), COUNT(*)
                FROM chunks
                WHERE primary_country = %s AND date IS NOT NULL AND date != '';
            """, (country,))
            row = cur.fetchone()
            if row and row[0]:
                return {"min": row[0], "max": row[1], "count": row[2]}
            return {"min": None, "max": None, "count": 0}
        finally:
            cur.close()

    def get_chunks_by_country(
        self,
        country: str,
        limit: int = 2000,
    ) -> List[Dict]:
        """Get all chunks for a given country."""
        cur = self._get_cursor()
        try:
            cur.execute("""
                SELECT
                    id, report_id, chunk_index, source_type, content,
                    title, date, source, primary_country, all_countries, themes, url,
                    embedding
                FROM chunks
                WHERE primary_country = %s
                ORDER BY date DESC
                LIMIT %s;
            """, (country, limit))

            columns = [
                "id", "report_id", "chunk_index", "source_type", "text",
                "title", "date", "source", "primary_country", "all_countries",
                "themes", "url", "embedding"
            ]
            results = []
            for row in cur.fetchall():
                entry = dict(zip(columns, row))
                # Convert embedding to list for compatibility
                if entry.get("embedding") is not None:
                    entry["embedding"] = _parse_embedding(entry["embedding"])
                results.append(entry)
            return results
        finally:
            cur.close()

    def get_chunks_by_country_and_themes(
        self,
        country: str,
        themes: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 2000,
    ) -> List[Dict]:
        """
        Country filter is required; themes and date range are optional.
        Uses SQL for efficient filtering.
        """
        conditions = ["primary_country = %s"]
        params: list = [country]

        if themes:
            # Exact theme matching: split comma-separated themes column and match exactly
            # Uses ANY with array literal for precise matching (avoids substring false positives)
            theme_conditions = []
            for t in themes:
                theme_conditions.append(
                    "(themes ILIKE %s OR themes ILIKE %s OR themes ILIKE %s OR themes = %s)"
                )
                # Match: "Health, ..." | "..., Health, ..." | "..., Health" | exact "Health"
                params.append(f"{t},%")
                params.append(f"%, {t},%")
                params.append(f"%, {t}")
                params.append(t)
            conditions.append(f"({ ' OR '.join(theme_conditions) })")

        if date_from:
            conditions.append("date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("date <= %s")
            params.append(date_to)

        where = " AND ".join(conditions)
        params.append(limit)

        cur = self._get_cursor()
        try:
            cur.execute(f"""
                SELECT
                    id, report_id, chunk_index, source_type, content,
                    title, date, source, primary_country, all_countries, themes, url,
                    embedding
                FROM chunks
                WHERE {where}
                ORDER BY date DESC
                LIMIT %s;
            """, params)

            columns = [
                "id", "report_id", "chunk_index", "source_type", "text",
                "title", "date", "source", "primary_country", "all_countries",
                "themes", "url", "embedding"
            ]
            results = []
            for row in cur.fetchall():
                entry = dict(zip(columns, row))
                if entry.get("embedding") is not None:
                    entry["embedding"] = _parse_embedding(entry["embedding"])
                results.append(entry)
            return results
        finally:
            cur.close()

    # -------------------------------------------------------------------------
    # SEMANTIC RETRIEVAL (RAG)
    # -------------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        country: Optional[str] = None,
        k: int = RETRIEVAL_TOP_K,
        candidate_pool: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """
        Returns the k closest chunks to the query.

        If candidate_pool is provided, filters the pool first;
        if not, searches the entire database.
        """
        if candidate_pool is not None:
            return self._retrieve_from_pool(query, candidate_pool, k)

        # Compute query embedding
        query_embedding = self.ef([query])[0]
        emb_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        conditions = []
        params: list = []

        if country:
            conditions.append("primary_country = %s")
            params.append(country)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        params.extend([emb_str, emb_str, k])

        cur = self._get_cursor()
        try:
            cur.execute(f"""
                SELECT
                    report_id, chunk_index, source_type, content,
                    title, date, source, primary_country, all_countries, themes, url,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM chunks
                {where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """, params)

            results = []
            for rank, row in enumerate(cur.fetchall(), start=1):
                (
                    report_id, chunk_index, source_type, content,
                    title, date, source, primary_country, all_countries, themes, url,
                    similarity
                ) = row
                results.append({
                    "rank": rank,
                    "similarity": round(float(similarity), 3),
                    "id": f"{report_id}_{chunk_index}",
                    "text": content,
                    "title": title,
                    "url": url,
                    "source": source,
                    "date": date,
                    "themes": themes,
                    "primary_country": primary_country,
                    "all_countries": all_countries,
                })
            return results
        finally:
            cur.close()

    def retrieve_bulk(
        self,
        queries: List[str],
        country: Optional[str] = None,
        k: int = RETRIEVAL_TOP_K,
        candidate_pool: Optional[List[Dict]] = None,
    ) -> List[List[Dict]]:
        """Bulk retrieval for multiple queries."""
        return [
            self.retrieve(q, country=country, k=k, candidate_pool=candidate_pool)
            for q in queries
        ]

    def _retrieve_from_pool(
        self, query: str, pool: List[Dict], k: int
    ) -> List[Dict]:
        """
        Compares chunks in the pool against the query and returns top-k.
        Uses numpy for cosine similarity computation.
        """
        if np is None:
            raise ImportError("numpy is required for pool-based retrieval")

        query_emb = self.ef([query])[0]
        query_vec = np.array(query_emb, dtype=float)

        scored = []
        for chunk in pool:
            chunk_emb = chunk.get("embedding")
            if chunk_emb is None:
                continue
            # Ensure embedding is a proper list of floats (not a string)
            chunk_emb = _parse_embedding(chunk_emb)
            if chunk_emb is None:
                continue
            chunk_vec = np.array(chunk_emb, dtype=float)
            denom = (np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec))
            sim = float(np.dot(query_vec, chunk_vec) / denom) if denom > 0 else 0.0
            scored.append((sim, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for rank, (sim, chunk) in enumerate(scored[:k], start=1):
            results.append({
                "rank": rank,
                "similarity": round(sim, 3),
                "id": chunk.get("id", ""),
                "text": chunk.get("text", ""),
                "title": chunk.get("title", ""),
                "url": chunk.get("url", ""),
                "source": chunk.get("source", ""),
                "date": chunk.get("date", ""),
                "themes": chunk.get("themes", ""),
                "primary_country": chunk.get("primary_country", ""),
            })
        return results

    # -------------------------------------------------------------------------
    # CONNECTION MANAGEMENT
    # -------------------------------------------------------------------------

    def close(self):
        """Close the database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()


# ============================================================================
# FACTORY
# ============================================================================

def get_pgvector_store(db_url: str = DB_URL) -> PgVectorStore:
    """Create and return a PgVectorStore instance."""
    store = PgVectorStore(db_url)
    store.ensure_schema()
    return store