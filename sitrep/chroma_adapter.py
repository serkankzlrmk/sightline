"""
sitrep_pipeline/chroma_adapter.py
Data retrieval and semantic retrieval operations on Chroma DB.

Replaces Stage 0 (file reading) and ColBERT retrieval from the original pipeline.
"""

import os
from typing import List, Dict, Optional

os.environ["ORT_LOGGING_LEVEL"] = "3"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from config import (
    CHROMA_DIR,
    CHROMA_COLLECTION,
    RETRIEVAL_TOP_K,
    RETRIEVAL_TOP_K_SUMMARY,
)


class ChromaAdapter:
    """
    Provides access to the reliefweb_chunks collection.

    Chunk schema:
        id         : "{report_id}_{chunk_index}"
        document   : raw text
        metadata   : {
            report_id, chunk_index, source_type,
            title, date, source,
            primary_country, all_countries, themes, url
        }
    """

    def __init__(self) -> None:
        self.client = chromadb.PersistentClient(path=CHROMA_DIR)
        self.ef = DefaultEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=self.ef,
        )

    # ------------------------------------------------------------------
    # Info / statistics
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Total chunk count in the collection."""
        return self.collection.count()

    def list_countries(self) -> List[str]:
        """Returns unique primary_country values in the DB."""
        results = self.collection.get(include=["metadatas"])
        countries = {m.get("primary_country", "") for m in results["metadatas"]}
        countries.discard("")
        return sorted(countries)

    def list_themes(self) -> List[str]:
        """Returns unique theme values in the DB."""
        results = self.collection.get(include=["metadatas"])
        themes: set = set()
        for m in results["metadatas"]:
            raw = m.get("themes", "")
            if raw:
                for t in raw.split(","):
                    t = t.strip()
                    if t:
                        themes.add(t)
        return sorted(themes)

    def get_date_range(self, country: str) -> Dict:
        """Returns the available date range for a given country."""
        chunks = self.get_chunks_by_country(country, limit=5000)
        if not chunks:
            return {"min": None, "max": None, "count": 0}
        dates = sorted(set(c.get("date", "")[:10] for c in chunks if c.get("date")))
        return {
            "min": dates[0] if dates else None,
            "max": dates[-1] if dates else None,
            "count": len(chunks),
        }

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

        Returns:
            [{id, text, title, url, source, date, themes, primary_country}]
        """
        results = self.collection.get(
            where={"primary_country": {"$eq": country}},
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

        query_emb = self.ef([query])[0]
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
