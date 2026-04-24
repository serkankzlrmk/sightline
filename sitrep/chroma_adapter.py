"""
sitrep_pipeline/chroma_adapter.py
Chroma DB üzerinde veri çekme ve semantic retrieval işlemleri.

Orijinal pipeline'daki Stage 0 (dosya okuma) ve ColBERT retrieval'ın yerini alır.
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
    reliefweb_chunks koleksiyonuna erişim sağlar.

    Chunk şeması:
        id         : "{report_id}_{chunk_index}"
        document   : ham metin
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
    # Bilgi / istatistik
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Koleksiyondaki toplam chunk sayısı."""
        return self.collection.count()

    def list_countries(self) -> List[str]:
        """DB'deki benzersiz primary_country değerlerini döndür."""
        results = self.collection.get(include=["metadatas"])
        countries = {m.get("primary_country", "") for m in results["metadatas"]}
        countries.discard("")
        return sorted(countries)

    def list_themes(self) -> List[str]:
        """DB'deki benzersiz tema değerlerini döndür."""
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
        """Belirli bir ülke için mevcut tarih aralığını döndür."""
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
    # Veri çekme
    # ------------------------------------------------------------------

    def get_chunks_by_country(
        self,
        country: str,
        limit: int = 2000,
    ) -> List[Dict]:
        """
        Belirli bir ülkeye ait tüm chunk'ları döndür.

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
        Ülke filtresi zorunlu; temalar ve tarih aralığı opsiyonel.
        themes: OR mantığı ile filtreler. Boşsa sadece ülke filtresine göre çeker.
        date_from / date_to: ISO format (YYYY-MM-DD). Chunk metadata 'date' alanına göre filtreler.

        Returns:
            [{id, text, title, url, source, date, themes, primary_country}]
        """
        if not themes and not date_from and not date_to:
            return self.get_chunks_by_country(country, limit)

        # Chroma'nın $contains operatörü olmadığı için ülkeden çekip Python'da filtrele
        raw = self.get_chunks_by_country(country, limit=limit * 2)
        filtered = raw

        # Tema filtresi (OR mantığı)
        if themes:
            filtered = [
                c for c in filtered
                if any(t.lower() in c["themes"].lower() for t in themes)
            ]

        # Tarih filtresi
        if date_from or date_to:
            def _date_in_range(chunk_date: str) -> bool:
                if not chunk_date:
                    return False
                d = chunk_date[:10]  # "YYYY-MM-DD" kısmını al
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
        Sorguya en yakın k chunk'ı döndür.

        candidate_pool verilirse (küme filtreleme için) önce pool'u filtreler;
        verilmezse tüm koleksiyonda arama yapar.

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
        Birden fazla sorgu için toplu retrieval (RRF öncesi kullanılır).
        Her sorgu için ayrı bir sonuç listesi döndür.
        """
        return [
            self.retrieve(q, country=country, k=k, candidate_pool=candidate_pool)
            for q in queries
        ]

    # ------------------------------------------------------------------
    # Yardımcı
    # ------------------------------------------------------------------

    def _retrieve_from_pool(
        self, query: str, pool: List[Dict], k: int
    ) -> List[Dict]:
        """
        Pool içindeki chunk'ları sorguyla karşılaştırarak top-k döndür.
        Embedding hesaplaması için DefaultEmbeddingFunction kullanır.
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
        """get() sonuçlarını standart dict listesine çevirir."""
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
        """query() sonuçlarını standart dict listesine çevirir."""
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
