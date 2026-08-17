"""
sitrep_pipeline/chroma_adapter.py
Data retrieval and semantic retrieval operations on vector store.

    Uses local ChromaDB for live vector storage.
"""

import logging
import os

os.environ["ORT_LOGGING_LEVEL"] = "3"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

from config import (
    CHROMA_COLLECTION,
    CHROMA_DIR,
    RETRIEVAL_TOP_K,
)

logger = logging.getLogger(__name__)


class ChromaAdapter:
    """
    Provides access to the reliefweb_chunks collection.

    Supports two backends:
      - ChromaDB (local, default)
      - pgvector (Supabase cloud)

    Chunk schema:
        id         : "{report_id}_{chunk_index}"
        document   : raw text
        metadata   : {
            report_id, chunk_index, source_type,
            title, date, source,
            primary_country, all_countries, themes, url
        }
    """

    def __init__(self, backend: str = None) -> None:
        if backend and backend != "chromadb":
            raise ValueError("Only ChromaDB is supported by this deployment")
        self.backend = "chromadb"
        self._pgvector = None
        self._countries_cache = None  # Cache for list_countries()
        self._countries_with_counts_cache = None  # Cache for list_countries_with_counts()

        if self.backend == "chromadb":
            import chromadb
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            self.client = chromadb.PersistentClient(path=CHROMA_DIR)
            self.ef = DefaultEmbeddingFunction()
            self.collection = self.client.get_or_create_collection(
                name=CHROMA_COLLECTION,
                embedding_function=self.ef,
                metadata={"hnsw:space": "cosine"},
            )
        else:
            raise ValueError("Only ChromaDB is supported by this deployment")

    def _get_pgvector(self):
        """Lazy-initialize pgvector store."""
        if self._pgvector is None:
            from reliefweb_api.pgvector_store import PgVectorStore

            self._pgvector = PgVectorStore()
            self._pgvector.ensure_schema()
        return self._pgvector

    # ------------------------------------------------------------------
    # Info / statistics
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Total chunk count in the collection.

        Uses SQLite (chunks table) — ChromaDB's collection.count() is
        UNRELIABLE on ARM64 production (sporadic SIGSEGV, untrappable).
        SQLite count is exact (chunks are written there at ingest) and safe.
        """
        try:
            import sqlite3

            from config import DB_PATH

            conn = sqlite3.connect(str(DB_PATH))
            try:
                row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except Exception:
            pass
        # ChromaDB fallback REMOVED — collection.count() segfaults on ARM64
        # (untrappable C-level crash). SQLite failing means something is
        # broken anyway; returning 0 is safer than killing the process.
        if self.backend == "pgvector":
            return self._get_pgvector().count()
        return 0

    def list_countries(self) -> list[str]:
        """Returns unique primary_country values — cached after first call."""
        if self._countries_cache is not None:
            return self._countries_cache
        result = self._list_countries_uncached()
        self._countries_cache = result
        return result

    def _list_countries_uncached(self) -> list[str]:
        """Internal: fetches unique primary_country values from backend."""
        # Try pgvector first
        if self.backend == "pgvector":
            try:
                countries = self._get_pgvector().list_countries()
                if countries:
                    return countries
            except Exception:
                pass
            # SQLite fallback
            return self._sqlite_list_countries()

        # ARM64 SAFETY (Aug 2026): ChromaDB collection.count() and large
        # collection.get() SEGFAULT the whole process on ARM64 (Hetzner).
        # The try/except below cannot catch a C-level SIGSEGV — the process
        # dies silently. Go straight to SQLite; ChromaDB metadata scan is
        # never worth the crash risk.
        return self._sqlite_list_countries()

    def list_themes(self) -> list[str]:
        """Returns unique theme values — pgvector or ChromaDB, then SQLite fallback."""
        # Try pgvector first
        if self.backend == "pgvector":
            try:
                themes = self._get_pgvector().list_themes()
                if themes:
                    return themes
            except Exception:
                pass
            # SQLite fallback
            return self._sqlite_list_themes()

        # ChromaDB path — SKIPPED on ARM64 (count()/get() segfault, see
        # _list_countries_uncached). Straight to SQLite.
        return self._sqlite_list_themes()

    def get_date_range(self, country: str) -> dict:
        """Returns the available date range for a given country.
        Uses metadata-only query (no embeddings) for performance."""
        normalized = self._normalize_country(country)

        # Try pgvector first
        if self.backend == "pgvector":
            try:
                result = self._get_pgvector().get_date_range(normalized)
                if result.get("min"):
                    return result
            except Exception:
                pass
            # SQLite fallback
            return self._sqlite_get_date_range(normalized, country)

        # ChromaDB path — SKIPPED on ARM64 (count()/get() segfault, see
        # _list_countries_uncached). SQLite carries the same data (chunks
        # table written at ingest) and is crash-safe.
        return self._sqlite_get_date_range(normalized, country)

    # ------------------------------------------------------------------
    # Country name normalization
    # ------------------------------------------------------------------

    _COUNTRY_ALIASES = {
        "syria": "Syria",
        "syrian arab republic": "Syria",
        "ukraine": "Ukraine",
        "sudan": "Sudan",
        "south sudan": "South Sudan",
        "democratic republic of the congo": "Democratic Republic of the Congo",
        "drc": "Democratic Republic of the Congo",
        "dr congo": "Democratic Republic of the Congo",
        "congo": "Republic of the Congo",
        "afghanistan": "Afghanistan",
        "yemen": "Yemen",
        "myanmar": "Myanmar",
        "burma": "Myanmar",
        "ethiopia": "Ethiopia",
        "somalia": "Somalia",
        "nigeria": "Nigeria",
        "haiti": "Haiti",
        "occupied palestinian territory": "occupied Palestinian territory",
        "palestine": "occupied Palestinian territory",
        "gaza": "occupied Palestinian territory",
        "israel": "Israel",
        "lebanon": "Lebanon",
        "iraq": "Iraq",
        "libya": "Libya",
        "mali": "Mali",
        "niger": "Niger",
        "cameroon": "Cameroon",
        "burkina faso": "Burkina Faso",
        "central african republic": "Central African Republic",
        "car": "Central African Republic",
        "chad": "Chad",
        "mozambique": "Mozambique",
        "bangladesh": "Bangladesh",
        "philippines": "Philippines",
        "pakistan": "Pakistan",
        "india": "India",
        "kenya": "Kenya",
        "tanzania": "Tanzania",
        "uganda": "Uganda",
        "zimbabwe": "Zimbabwe",
        "venezuela": "Venezuela",
        "colombia": "Colombia",
        "ecuador": "Ecuador",
        "peru": "Peru",
        "brazil": "Brazil",
        "turkey": "Türkiye",
        "turkiye": "Türkiye",
    }

    def _normalize_country(self, country: str) -> str:
        """Normalize a country name for ChromaDB query.

        Tries alias map first, then falls back to checking available
        countries for a case-insensitive exact match.
        Partial/substring matching is intentionally avoided to prevent
        false positives (e.g. 'Sudan' matching 'South Sudan').
        """
        lower = country.strip().lower()
        # Check alias map
        if lower in self._COUNTRY_ALIASES:
            return self._COUNTRY_ALIASES[lower]
        # Check exact match against available countries
        available = self.list_countries()
        for c in available:
            if c.lower() == lower:
                return c
        # No match found — return original (will likely return 0 results)
        return country

    def list_countries_with_counts(self) -> list[dict]:
        """Returns countries with chunk counts, sorted by count descending.
        Useful for UI dropdowns to show data availability."""
        if self._countries_with_counts_cache is not None:
            return self._countries_with_counts_cache

        if self.backend == "pgvector":
            try:
                result = self._get_pgvector().list_countries_with_counts()
                self._countries_with_counts_cache = result
                return result
            except Exception:
                pass

        result = self._sqlite_list_countries_with_counts()
        self._countries_with_counts_cache = result
        return result

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------

    def get_chunks_by_country(
        self,
        country: str,
        limit: int = 2000,
    ) -> list[dict]:
        """
        Returns all chunks belonging to a given country.
        Searches both primary_country and all_countries to catch multi-country reports.

        NOTE: reads chunks from SQLite (chunks + reports join) — ChromaDB's
        collection.get() with large result sets segfaults on ARM64 production
        (SIGSEGV, untrappable). SQLite holds the same chunk data written at
        ingest. Embeddings are NOT included (clustering re-embeds on demand).

        Returns:
            [{id, text, title, url, source, date, themes, primary_country}]
        """
        normalized = self._normalize_country(country)

        if self.backend == "pgvector":
            return self._get_pgvector().get_chunks_by_country(normalized, limit=limit)

        try:
            import json as _json
            import sqlite3

            from config import DB_PATH

            conn = sqlite3.connect(str(DB_PATH))
            try:
                report_ids = self._sqlite_find_report_ids_by_country(normalized, limit=limit)
                if not report_ids:
                    return []
                placeholders = ",".join("?" * len(report_ids))
                rows = conn.execute(
                    f"""
                    SELECT c.id, c.report_id, c.chunk_index, c.content,
                           r.title, r.date, r.source, r.url, r.countries, r.themes
                    FROM chunks c
                    JOIN reports r ON c.report_id = r.report_id
                    WHERE c.report_id IN ({placeholders})
                    ORDER BY c.report_id, c.chunk_index
                    LIMIT ?
                    """,
                    (*report_ids, limit),
                ).fetchall()
            finally:
                conn.close()

            output = []
            for row in rows:
                (
                    cid, report_id, chunk_index, content,
                    title, date, source, url, countries_raw, themes_raw,
                ) = row
                try:
                    countries = _json.loads(countries_raw) if countries_raw else []
                except Exception:
                    countries = []
                try:
                    themes_list = _json.loads(themes_raw) if themes_raw else []
                except Exception:
                    themes_list = []
                # ChromaDB-style id: "{report_id}_{chunk_index}"
                chroma_id = f"{report_id}_{chunk_index}"
                # primary_country: prefer the queried country; fall back to the
                # first listed country (some reports list "World" first).
                if normalized in countries:
                    primary = normalized
                else:
                    primary = countries[0] if countries else normalized
                output.append(
                    {
                        "id": chroma_id,
                        "text": content or "",
                        "title": title or "",
                        "url": url or "",
                        "source": source or "",
                        "date": date or "",
                        "themes": ", ".join(themes_list) if themes_list else "",
                        "primary_country": primary,
                        "all_countries": ", ".join(countries) if countries else "",
                    }
                )
            return output
        except Exception as exc:
            # ChromaDB fallback REMOVED — collection.get() segfaults on ARM64.
            # SQLite read failing means something is broken; return [] instead
            # of risking a process-killing C-level crash.
            logger.warning("SQLite chunk read failed for %s: %s — returning empty", country, exc)
            return []

    def get_chunks_by_country_and_themes(
        self,
        country: str,
        themes: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 2000,
    ) -> list[dict]:
        """
        Country filter is required; themes and date range are optional.
        themes: Filters with OR logic. If empty, fetches by country filter only.
        date_from / date_to: ISO format (YYYY-MM-DD). Filters by chunk metadata 'date' field.

        Returns:
            [{id, text, title, url, source, date, themes, primary_country}]
        """
        if self.backend == "pgvector":
            normalized = self._normalize_country(country)
            return self._get_pgvector().get_chunks_by_country_and_themes(
                normalized, themes=themes, date_from=date_from, date_to=date_to, limit=limit
            )

        # ChromaDB path
        if not themes and not date_from and not date_to:
            return self.get_chunks_by_country(country, limit)

        # Chroma lacks $contains operator, so fetch by country and filter in Python
        raw = self.get_chunks_by_country(country, limit=limit * 2)
        filtered = raw

        # Theme filter (OR logic, exact match after splitting comma-separated themes)
        if themes:
            themes_lower = {t.strip().lower() for t in themes}
            filtered = [
                c for c in filtered if any(ct.strip().lower() in themes_lower for ct in c.get("themes", "").split(","))
            ]

        # Date filter
        if date_from or date_to:

            def _date_in_range(chunk_date: str) -> bool:
                if not chunk_date:
                    return False
                d = chunk_date[:10]  # Take the "YYYY-MM-DD" part
                if date_from and d < date_from:
                    return False
                if date_to and d > date_to:
                    return False
                return True

            filtered = [c for c in filtered if _date_in_range(c.get("date", ""))]

        return filtered[:limit]

    # ------------------------------------------------------------------
    # Semantic retrieval (RAG)
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        country: str | None = None,
        k: int = RETRIEVAL_TOP_K,
        candidate_pool: list[dict] | None = None,
    ) -> list[dict]:
        """
        Returns the k closest chunks to the query.

        If candidate_pool is provided (for cluster filtering), filters the pool first;
        if not provided, searches the entire collection.

        Returns:
            [{rank, similarity, id, text, title, url, source, date, themes, primary_country}]
        """
        if self.backend == "pgvector":
            return self._get_pgvector().retrieve(query, country=country, k=k, candidate_pool=candidate_pool)

        # ChromaDB path
        if candidate_pool is not None:
            # Custom pool: embedding similarities with numpy.
            # NOTE: must NOT call collection.count() first — that segfaults on
            # ARM64 production. Pool path needs no collection access at all.
            return self._retrieve_from_pool(query, candidate_pool, k)

        # Whole-collection path — DISABLED on ARM64: collection.query() and
        # count() both segfault (untrappable C-level crash). The SITREP
        # pipeline always passes a candidate_pool (clustering output), so
        # this path is only hit by ad-hoc RAG calls — returning [] with a
        # warning is safer than killing the process.
        logger.warning(
            "retrieve() whole-collection path called without candidate_pool — "
            "unsafe on ARM64 (ChromaDB query segfault); returning empty"
        )
        return []

    def retrieve_bulk(
        self,
        queries: list[str],
        country: str | None = None,
        k: int = RETRIEVAL_TOP_K,
        candidate_pool: list[dict] | None = None,
    ) -> list[list[dict]]:
        """
        Bulk retrieval for multiple queries (used before RRF).
        Returns a separate result list for each query.
        """
        if self.backend == "pgvector":
            return self._get_pgvector().retrieve_bulk(queries, country=country, k=k, candidate_pool=candidate_pool)

        # ChromaDB path
        return [self.retrieve(q, country=country, k=k, candidate_pool=candidate_pool) for q in queries]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _retrieve_from_pool(self, query: str, pool: list[dict], k: int) -> list[dict]:
        """
        Compares chunks in the pool against the query and returns top-k.
        Uses DefaultEmbeddingFunction for embedding computation.
        """
        import numpy as np

        # ARM64 safety: if pool chunks lack embeddings (ChromaDB can't return
        # them without segfaulting), re-embed the missing texts on demand.
        missing = [i for i, c in enumerate(pool) if c.get("embedding") is None]
        if missing:
            try:
                from sitrep.clustering import _embed_missing

                _embed_missing(pool, missing)
            except Exception:
                pass

        # Get the right embedding function based on backend
        if self.backend == "pgvector":
            ef = self._get_pgvector().ef
        else:
            ef = self.ef

        query_emb = ef([query])[0]
        query_vec = np.array(query_emb, dtype=float)

        scored = []
        for chunk in pool:
            chunk_emb = chunk.get("embedding")
            if chunk_emb is None:
                continue
            # Handle string embeddings from pgvector/psycopg2
            if isinstance(chunk_emb, str):
                import json as _json

                try:
                    chunk_emb = _json.loads(chunk_emb)
                except (ValueError, _json.JSONDecodeError):
                    stripped = chunk_emb.strip()
                    if stripped.startswith("[") and stripped.endswith("]"):
                        stripped = stripped[1:-1]
                    chunk_emb = [float(x) for x in stripped.split(",") if x.strip()]
            chunk_vec = np.array(chunk_emb, dtype=float)
            # Cosine similarity
            denom = np.linalg.norm(query_vec) * np.linalg.norm(chunk_vec)
            sim = float(np.dot(query_vec, chunk_vec) / denom) if denom > 0 else 0.0
            scored.append((sim, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for rank, (sim, chunk) in enumerate(scored[:k], start=1):
            results.append(
                {
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
                }
            )
        return results

    def _format_results(self, results: dict) -> list[dict]:
        """Converts get() results to a standard dict list."""
        ids = results.get("ids", [])
        docs = results.get("documents")
        if docs is None:
            docs = [None] * len(ids)
        metas = results.get("metadatas")
        if metas is None:
            metas = [{}] * len(ids)
        embeddings = results.get("embeddings")
        if embeddings is None:
            embeddings = [None] * len(ids)

        output = []
        for cid, doc, meta, emb in zip(ids, docs, metas, embeddings, strict=False):
            entry = {
                "id": cid,
                "text": doc or "",
                "title": meta.get("title", ""),
                "url": meta.get("url", ""),
                "source": meta.get("source", ""),
                "date": meta.get("date", ""),
                "themes": meta.get("themes", ""),
                "primary_country": meta.get("primary_country", ""),
                "all_countries": meta.get("all_countries", ""),
            }
            if emb is not None:
                import numpy as np

                if isinstance(emb, str):
                    import json as _json

                    try:
                        emb = _json.loads(emb)
                    except (ValueError, _json.JSONDecodeError):
                        stripped = emb.strip()
                        if stripped.startswith("[") and stripped.endswith("]"):
                            stripped = stripped[1:-1]
                        emb = [float(x) for x in stripped.split(",") if x.strip()]
                entry["embedding"] = emb.tolist() if isinstance(emb, np.ndarray) else list(emb)
            output.append(entry)
        return output

    def _format_query_results(self, results: dict) -> list[dict]:
        """Converts query() results to a standard dict list."""
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]

        output = []
        for rank, (doc, meta, dist) in enumerate(zip(docs, metas, dists, strict=False), start=1):
            output.append(
                {
                    "rank": rank,
                    "similarity": round(1 - dist, 3),
                    "id": f"{meta.get('report_id', '')}_{meta.get('chunk_index', '')}",
                    "text": doc,
                    "title": meta.get("title", ""),
                    "url": meta.get("url", ""),
                    "source": meta.get("source", ""),
                    "date": meta.get("date", ""),
                    "themes": meta.get("themes", ""),
                    "primary_country": meta.get("primary_country", ""),
                    "all_countries": meta.get("all_countries", ""),
                }
            )
        return output

    # ------------------------------------------------------------------
    # SQLite fallback methods (used when vector store is unavailable)
    # ------------------------------------------------------------------

    def _sqlite_list_countries(self) -> list[str]:
        """SQLite fallback for list_countries."""
        try:
            import json as _json
            import sqlite3

            from config import DB_PATH

            conn = sqlite3.connect(str(DB_PATH))
            rows = conn.execute(
                "SELECT countries FROM reports WHERE countries IS NOT NULL AND countries != '[]'"
            ).fetchall()
            conn.close()
            countries_set = set()
            for row in rows:
                try:
                    for c in _json.loads(row[0]):
                        if c and isinstance(c, str):
                            countries_set.add(c.strip())
                except (ValueError, TypeError):
                    pass
            return sorted(countries_set)
        except Exception:
            return []

    def _sqlite_list_themes(self) -> list[str]:
        """SQLite fallback for list_themes."""
        try:
            import json as _json
            import sqlite3

            from config import DB_PATH

            conn = sqlite3.connect(str(DB_PATH))
            rows = conn.execute("SELECT themes FROM reports WHERE themes IS NOT NULL AND themes != '[]'").fetchall()
            conn.close()
            themes_set = set()
            for row in rows:
                try:
                    for t in _json.loads(row[0]):
                        if t and isinstance(t, str):
                            themes_set.add(t.strip())
                except (ValueError, TypeError):
                    pass
            return sorted(themes_set)
        except Exception:
            return []

    def _sqlite_get_date_range(self, normalized: str, country: str) -> dict:
        """SQLite fallback for get_date_range."""
        try:
            import json as _json
            import sqlite3

            from config import DB_PATH

            conn = sqlite3.connect(str(DB_PATH))
            rows = conn.execute(
                "SELECT date, countries FROM reports WHERE countries IS NOT NULL AND countries != '[]'"
            ).fetchall()
            conn.close()
            dates = []
            for r in rows:
                try:
                    cs = _json.loads(r[1])
                    if normalized in cs or country in cs:
                        if r[0]:
                            dates.append(r[0][:10])
                except (ValueError, TypeError):
                    pass
            if dates:
                return {"min": min(dates), "max": max(dates), "count": len(dates)}
        except Exception:
            pass
        return {"min": None, "max": None, "count": 0}

    def _sqlite_find_report_ids_by_country(self, country: str, limit: int = 2000) -> list[int]:
        """Find report IDs that mention a country (in the countries JSON array)."""
        try:
            import json as _json
            import sqlite3

            from config import DB_PATH

            conn = sqlite3.connect(str(DB_PATH))
            rows = conn.execute(
                "SELECT report_id, countries FROM reports WHERE countries IS NOT NULL AND countries != '[]'"
            ).fetchall()
            conn.close()

            country_lower = country.strip().lower()
            aliases = {
                "syria": "syrian arab republic",
                "turkey": "türkiye",
                "iran": "iran (islamic republic of)",
                "dr congo": "democratic republic of the congo",
                "opt": "occupied palestinian territory",
            }
            alias_lower = aliases.get(country_lower, country_lower)

            ids = []
            for rid, countries_json in rows:
                try:
                    countries = _json.loads(countries_json)
                    for c in countries:
                        c_lower = c.strip().lower()
                        if c_lower == country_lower or c_lower == alias_lower:
                            ids.append(rid)
                            break
                except (ValueError, TypeError):
                    pass
            return ids[:limit]
        except Exception:
            return []

    def _sqlite_list_countries_with_counts(self) -> list[dict]:
        """SQLite fallback for list_countries_with_counts.
        Parses the `countries` JSON array column (each report may list multiple countries).
        """
        try:
            import json as _json
            import sqlite3

            from config import DB_PATH

            conn = sqlite3.connect(str(DB_PATH))
            rows = conn.execute(
                "SELECT countries FROM reports WHERE countries IS NOT NULL AND countries != '[]'"
            ).fetchall()
            conn.close()
            counts: dict[str, int] = {}
            for row in rows:
                try:
                    for c in _json.loads(row[0]):
                        if c and isinstance(c, str):
                            c = c.strip()
                            if c:
                                counts[c] = counts.get(c, 0) + 1
                except (ValueError, TypeError):
                    pass
            result = sorted(
                [{"name": k, "count": v} for k, v in counts.items()],
                key=lambda x: x["count"],
                reverse=True,
            )
            return result
        except Exception:
            return []
