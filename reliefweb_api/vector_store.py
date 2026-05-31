"""
ReliefWeb Vector Store
Persistent semantic search over ingested report chunks.

Supports two backends:
  - 'chromadb' (default): Uses local ChromaDB for vector storage
  - 'pgvector': Uses Supabase PostgreSQL + pgvector for cloud-hosted storage

Controlled by VECTOR_BACKEND env var (default: 'chromadb').

Usage:
    from reliefweb_api.vector_store import VectorStore

    vs = VectorStore()
    results = vs.search("Sudan flooding health", n_results=5, country="Sudan")
"""

import os
from pathlib import Path
from typing import List, Dict, Optional

from config import VECTOR_BACKEND

# Force ONNX Runtime to skip TensorRT provider — avoids ~3 sec retry on every query
os.environ.setdefault("ONNXRUNTIME_PROVIDERS", "CUDAExecutionProvider,CPUExecutionProvider")
os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "0")

# ============================================================================
# CONFIG
# ============================================================================

CHROMA_DIR = "reliefweb_chroma"
COLLECTION_NAME = "reliefweb_chunks"


# ============================================================================
# VECTOR STORE
# ============================================================================

class VectorStore:
    """
    Semantic search over ReliefWeb report chunks.

    Delegates to either ChromaDB or pgvector based on VECTOR_BACKEND config.
    """

    def __init__(self, persist_dir: str = CHROMA_DIR, backend: str = None):
        self.backend = backend or VECTOR_BACKEND
        self.persist_dir = persist_dir  # Store for get_stats()

        if self.backend == "pgvector":
            from reliefweb_api.pgvector_store import PgVectorStore
            self._pgvector = PgVectorStore()
            self._pgvector.ensure_schema()
            self._chroma = None
        elif self.backend == "chromadb":
            import chromadb
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            self.client = chromadb.PersistentClient(path=persist_dir)
            self.ef = DefaultEmbeddingFunction()
            self.collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=self.ef,
                metadata={"hnsw:space": "cosine"},
            )
            self._pgvector = None
            self._chroma = self
        else:
            raise ValueError(f"Unknown VECTOR_BACKEND: {self.backend!r}. Use 'chromadb' or 'pgvector'.")

    # -------------------------------------------------------------------------
    # DEDUPLICATION
    # -------------------------------------------------------------------------

    def report_exists(self, report_id: int) -> bool:
        """Fast check: does chunk 0 of this report exist in the vector DB?"""
        if self.backend == "pgvector":
            return self._pgvector.report_exists(report_id)
        # ChromaDB path
        result = self.collection.get(ids=[f"{report_id}_0"], include=[])
        return len(result["ids"]) > 0

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
        if self.backend == "pgvector":
            return self._pgvector.add_report(report_id, chunks, report_meta)

        # ChromaDB path
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
        primary_country = (
            countries[0].get("shortname", countries[0].get("name", ""))
            if countries else ""
        )
        all_countries = ", ".join(
            c.get("shortname", c.get("name", "")) for c in countries[:8]
        )
        themes = [t.get("name", "") for t in report_meta.get("themes", [])]
        themes_str = ", ".join(themes[:6])

        # ---- build ChromaDB lists ----
        ids = [f"{report_id}_{i}" for i in range(len(chunks))]
        documents = [c["content"] for c in chunks]
        metadatas = [
            {
                "report_id": report_id,
                "chunk_index": i,
                "source_type": chunks[i]["source_type"],
                "title": report_meta.get("title", ""),
                "date": date_str,
                "source": source_name,
                "primary_country": primary_country,
                "all_countries": all_countries,
                "themes": themes_str,
                "url": report_meta.get("url", ""),
            }
            for i in range(len(chunks))
        ]

        # ChromaDB handles batching internally
        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
        return len(chunks)

    # -------------------------------------------------------------------------
    # SEARCH
    # -------------------------------------------------------------------------

    def search(
        self,
        query: str,
        n_results: int = 5,
        country: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[Dict]:
        """
        Semantic search over all ingested chunks.

        Args:
            query: Natural language search query
            n_results: Max chunks to return
            country: Filter by primary_country (exact match)
            source: Filter by source org shortname (e.g. 'UNHCR')

        Returns:
            List of dicts with rank, similarity, report_id, title, date,
            source, countries, source_type, url, chunk_preview (first 400 chars)
        """
        if self.backend == "pgvector":
            return self._pgvector.search(query, n_results=n_results, country=country, source=source)

        # ChromaDB path
        total = self.collection.count()
        if total == 0:
            return []

        # Build optional where filter
        where = None
        conditions = []
        if country:
            conditions.append({"primary_country": {"$eq": country}})
        if source:
            conditions.append({"source": {"$eq": source}})

        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        results = self.collection.query(
            query_texts=[query],
            n_results=min(n_results, total),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append({
                "rank": len(output) + 1,
                "similarity": round(1 - dist, 3),
                "report_id": meta.get("report_id"),
                "title": meta.get("title"),
                "date": meta.get("date"),
                "source": meta.get("source"),
                "countries": meta.get("all_countries"),
                "source_type": meta.get("source_type"),
                "url": meta.get("url"),
                "chunk_preview": doc[:400],
            })

        return output

    # -------------------------------------------------------------------------
    # STATS
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict:
        if self.backend == "pgvector":
            return self._pgvector.get_stats()
        return {
            "total_chunks": self.collection.count(),
            "collection": COLLECTION_NAME,
            "persist_dir": str(Path(self.persist_dir).resolve()) if hasattr(self, 'persist_dir') and self.persist_dir else "N/A",
        }

    def purge_by_report_ids(self, report_ids: List[int]) -> int:
        """Remove all chunks belonging to the given report_ids.
        
        Returns the number of chunk IDs removed.
        """
        if self.backend == "pgvector":
            return self._pgvector.purge_by_report_ids(report_ids)

        # ChromaDB path
        if not report_ids:
            return 0
        # Build chunk IDs: "{report_id}_0", "{report_id}_1", ...
        # ChromaDB doesn't support prefix delete, so we query first
        chunk_ids_to_remove = []
        for rid in report_ids:
            # Find all chunks for this report_id
            try:
                results = self.collection.get(
                    where={"report_id": str(rid)},
                    include=[]
                )
                if results and results.get("ids"):
                    chunk_ids_to_remove.extend(results["ids"])
            except Exception:
                # Fallback: try common chunk indices
                for i in range(200):  # reasonable upper bound
                    chunk_ids_to_remove.append(f"{rid}_{i}")
        
        if not chunk_ids_to_remove:
            return 0
        
        # Deduplicate
        chunk_ids_to_remove = list(set(chunk_ids_to_remove))
        
        # Delete in batches (ChromaDB has limits)
        batch_size = 500
        total_removed = 0
        for i in range(0, len(chunk_ids_to_remove), batch_size):
            batch = chunk_ids_to_remove[i:i + batch_size]
            try:
                self.collection.delete(ids=batch)
                total_removed += len(batch)
            except Exception:
                pass
        
        return total_removed


# ============================================================================
# FACTORY
# ============================================================================

def get_vector_store(persist_dir: str = CHROMA_DIR, backend: str = None) -> VectorStore:
    return VectorStore(persist_dir, backend=backend)
