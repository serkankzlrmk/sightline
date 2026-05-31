"""
sitrep_pipeline/chroma_adapter.py
Data retrieval and semantic retrieval operations on vector store.

Supports two backends:
  - 'chromadb' (default): Uses local ChromaDB for vector storage
  - 'pgvector': Uses Supabase PostgreSQL + pgvector for cloud-hosted storage

Controlled by VECTOR_BACKEND env var (default: 'chromadb').
"""

import os
from typing import List, Dict, Optional

os.environ["ORT_LOGGING_LEVEL"] = "3"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

from config import (
    CHROMA_DIR,
    CHROMA_COLLECTION,
    VECTOR_BACKEND,
    RETRIEVAL_TOP_K,
    RETRIEVAL_TOP_K_SUMMARY,
)


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
        self.backend = backend or VECTOR_BACKEND
        self._pgvector = None  # Lazy init for pgvector

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
        elif self.backend == "pgvector":
            # Lazy init — will connect on first use
            self._pgvector = None
            self.ef = None  # Will be set when pgvector store is initialized
        else:
            raise ValueError(f"Unknown VECTOR_BACKEND: {self.backend!r}. Use 'chromadb' or 'pgvector'.")

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
        """Total chunk count in the collection."""
        if self.backend == "pgvector":
            return self._get_pgvector().count()
        return self.collection.count()

    def list_countries(self) -> List[str]:
        """Returns unique primary_country values — pgvector or ChromaDB, then SQLite fallback."""
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

        # ChromaDB path
        try:
            if self.collection.count() > 0:
                results = self.collection.get(include=["metadatas"])
                countries = {m.get("primary_country", "") for m in results["metadatas"]}
                countries.discard("")
                if countries:
                    return sorted(countries)
        except Exception:
            pass
        # SQLite fallback
        return self._sqlite_list_countries()

    def list_themes(self) -> List[str]:
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

        # ChromaDB path
        try:
            if self.collection.count() > 0:
                results = self.collection.get(include=["metadatas"])
                themes: set = set()
                for m in results["metadatas"]:
                    raw = m.get("themes", "")
                    if raw:
                        for t in raw.split(","):
                            t = t.strip()
                            if t:
                                themes.add(t)
                if themes:
                    return sorted(themes)
        except Exception:
            pass
        # SQLite fallback
        return self._sqlite_list_themes()

    def get_date_range(self, country: str) -> Dict:
        """Returns the available date range for a given country."""
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

        # ChromaDB path
        chunks = self.get_chunks_by_country(normalized, limit=5000)
        if chunks:
            dates = sorted(set(c.get("date", "")[:10] for c in chunks if c.get("date")))
            return {
                "min": dates[0] if dates else None,
                "max": dates[-1] if dates else None,
                "count": len(chunks),
            }
        # SQLite fallback
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
        countries for a case-insensitive match.
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
        # Check partial match
        for c in available:
            if lower in c.lower() or c.lower() in lower:
                return c
        # No match found — return original
        return country

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------

    def get_chunks_by_country(
        self,
        country: str,
        limit: int = 2000,
    ) -> List[Dict]:
        """
        Returns all chunks belonging to a given country.
        Normalizes country name for better matching.

        Returns:
            [{id, text, title, url, source, date, themes, primary_country}]
        """
        normalized = self._normalize_country(country)

        if self.backend == "pgvector":
            return self._get_pgvector().get_chunks_by_country(normalized, limit=limit)

        # ChromaDB path
        results = self.collection.get(
            where={"primary_country": {"$eq": normalized}},
            limit=limit,
            include=["documents", "metadatas", "embeddings"],
        )
        return self._format_results(results)

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

        # Theme filter (OR logic)
        if themes:
            filtered = [
                c for c in filtered
                if any(t.lower() in c["themes"].lower() for t in themes)
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
        country: Optional[str] = None,
        k: int = RETRIEVAL_TOP_K,
        candidate_pool: Optional[List[Dict]] = None,
    ) -> List[Dict]:
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
        total = self.collection.count()
        if total == 0:
            return []

        if candidate_pool is not None:
            # Custom pool: embedding similarities with numpy
            return self._retrieve_from_pool(query, candidate_pool, k)

        where = None
        if country:
            where = {"primary_country": {"$eq": country}}

        results = self.collection.query(
            query_texts=[query],
            n_results=min(k, total),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return self._format_query_results(results)

    def retrieve_bulk(
        self,
        queries: List[str],
        country: Optional[str] = None,
        k: int = RETRIEVAL_TOP_K,
        candidate_pool: Optional[List[Dict]] = None,
    ) -> List[List[Dict]]:
        """
        Bulk retrieval for multiple queries (used before RRF).
        Returns a separate result list for each query.
        """
        if self.backend == "pgvector":
            return self._get_pgvector().retrieve_bulk(queries, country=country, k=k, candidate_pool=candidate_pool)

        # ChromaDB path
        return [
            self.retrieve(q, country=country, k=k, candidate_pool=candidate_pool)
            for q in queries
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _retrieve_from_pool(
        self, query: str, pool: List[Dict], k: int
    ) -> List[Dict]:
        """
        Compares chunks in the pool against the query and returns top-k.
        Uses DefaultEmbeddingFunction for embedding computation.
        """
        import numpy as np

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
            chunk_vec = np.array(chunk_emb, dtype=float)
            # Cosine similarity
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

    def _format_results(self, results: Dict) -> List[Dict]:
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
        for cid, doc, meta, emb in zip(ids, docs, metas, embeddings):
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
                entry["embedding"] = emb.tolist() if isinstance(emb, np.ndarray) else list(emb)
            output.append(entry)
        return output

    def _format_query_results(self, results: Dict) -> List[Dict]:
        """Converts query() results to a standard dict list."""
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]

        output = []
        for rank, (doc, meta, dist) in enumerate(zip(docs, metas, dists), start=1):
            output.append({
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
            })
        return output

    # ------------------------------------------------------------------
    # SQLite fallback methods (used when vector store is unavailable)
    # ------------------------------------------------------------------

    def _sqlite_list_countries(self) -> List[str]:
        """SQLite fallback for list_countries."""
        try:
            import json as _json
            from config import DB_PATH
            import sqlite3
            conn = sqlite3.connect(str(DB_PATH))
            rows = conn.execute("SELECT countries FROM reports WHERE countries IS NOT NULL AND countries != '[]'").fetchall()
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

    def _sqlite_list_themes(self) -> List[str]:
        """SQLite fallback for list_themes."""
        try:
            import json as _json
            from config import DB_PATH
            import sqlite3
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

    def _sqlite_get_date_range(self, normalized: str, country: str) -> Dict:
        """SQLite fallback for get_date_range."""
        try:
            import json as _json
            from config import DB_PATH
            import sqlite3
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
