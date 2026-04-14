"""
sitrep_pipeline/clustering.py
Chunk'ları topic cluster'larına ayırır ve her cluster için bir başlık üretir.

Orijinal Stage 1 (1-clean-clustering.ipynb) mantığını alır ancak:
- Paragraph oluşturma adımı atlanır (Chroma chunk'ları zaten hazır)
- Embedding'ler Chroma'dan çekilir (yerel model gereksiz)
- LLM çağrıları OpenRouter üzerinden yapılır
"""

import json
import random
import re
import logging
from typing import List, Dict, Tuple, Optional

import numpy as np

from config import (
    UMAP_N_COMPONENTS,
    UMAP_METRIC,
    UMAP_MIN_DIST,
    HDBSCAN_METRIC,
    HDBSCAN_CLUSTER_SELECTION_METHOD,
    HP_N_NEIGHBORS_RANGE,
    HP_MIN_CLUSTER_SIZE_RANGE,
    HP_MIN_SAMPLES_RANGE,
    HP_EPSILON_OPTIONS,
    HP_SEARCH_ITERATIONS,
    HP_MIN_CLUSTERS,
    LLM_MAX_TOKENS_HEADLINE,
)
import llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding → UMAP → HDBSCAN
# ---------------------------------------------------------------------------

def _umap_reduce(embeddings: np.ndarray, n_neighbors: int) -> np.ndarray:
    """UMAP boyut indirgeme."""
    import umap as umap_lib

    reducer = umap_lib.UMAP(
        n_neighbors=n_neighbors,
        n_components=UMAP_N_COMPONENTS,
        metric=UMAP_METRIC,
        min_dist=UMAP_MIN_DIST,
        random_state=42,
    )
    return reducer.fit_transform(embeddings)


def _hdbscan_fit(
    umap_embs: np.ndarray,
    min_cluster_size: int,
    min_samples: int,
    epsilon: float,
) -> "hdbscan.HDBSCAN":
    """HDBSCAN cluster nesnesi oluştur ve fit et."""
    import hdbscan as hdbscan_lib

    clusterer = hdbscan_lib.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_epsilon=epsilon,
        metric=HDBSCAN_METRIC,
        cluster_selection_method=HDBSCAN_CLUSTER_SELECTION_METHOD,
        gen_min_span_tree=True,
    ).fit(umap_embs)
    return clusterer


def _dbcv_score(clusterer, prob_threshold: float = 0.05) -> Tuple[int, float]:
    """
    (label_count, dbcv_score) döndür.
    Noise (-1) olan etiketler sayılmaz.
    """
    labels = clusterer.labels_
    # Belirli bir güven eşiğinin altındaki noktaları gürültü olarak say
    labels = np.where(clusterer.probabilities_ >= prob_threshold, labels, -1)
    label_count = len(set(labels)) - (1 if -1 in labels else 0)
    dbcv = float(clusterer.relative_validity_)
    return label_count, dbcv


# ---------------------------------------------------------------------------
# LLM: Cluster kalite değerlendirmesi
# ---------------------------------------------------------------------------

_COHERENCE_SYSTEM = (
    "You are an expert evaluating humanitarian situation report clusters. "
    "You must respond ONLY with two numbers separated by a newline, nothing else."
)

_COHERENCE_USER_TEMPLATE = """\
Evaluate the coherence and homogeneity of the following cluster of humanitarian documents.

- **Coherence**: How logically connected are the items? Do they form a consistent narrative?
- **Homogeneity**: How similar are the items in topic, content, and style? Any outliers?

Documents:
{documents}

Respond ONLY with:
Coherence score (0 to 1)
Homogeneity score (0 to 1)

Example response:
0.82
0.75
"""


def _llm_coherence_score(paragraphs: List[str]) -> float:
    """
    Verilen paragraflar için LLM coherence + homogeneity ortalama skoru döndür.
    Ayrıştırma başarısız olursa 0.5 döndür.
    """
    sample = paragraphs[:8]  # LLM'ye max 8 paragraf gönder (token tasarrufu)
    docs_str = "\n---\n".join(
        f"[{i+1}] {p[:300]}" for i, p in enumerate(sample)
    )
    prompt = _COHERENCE_USER_TEMPLATE.format(documents=docs_str)

    try:
        response = llm_client.chat_simple(
            user_prompt=prompt,
            system_prompt=_COHERENCE_SYSTEM,
            max_tokens=32,
        )
        numbers = re.findall(r"[0-9]+\.?[0-9]*", response)
        if len(numbers) >= 2:
            return (float(numbers[0]) + float(numbers[1])) / 2.0
        elif len(numbers) == 1:
            return float(numbers[0])
    except Exception as exc:
        logger.warning("Failed to get LLM coherence score: %s", exc)
    return 0.5


def _evaluate_all_clusters_llm(
    chunks: List[Dict], labels: np.ndarray
) -> float:
    """
    Tüm cluster'lar için ortalama LLM coherence skoru.
    Her cluster'dan en fazla 6 chunk örneklenerek değerlendirilir.
    """
    unique_labels = [l for l in set(labels) if l != -1]
    if not unique_labels:
        return 0.0

    scores = []
    for label in unique_labels:
        cluster_chunks = [
            chunks[i]["text"]
            for i, lbl in enumerate(labels)
            if lbl == label
        ]
        sample = cluster_chunks[:6]
        score = _llm_coherence_score(sample)
        scores.append(score)

    return float(np.mean(scores))


# ---------------------------------------------------------------------------
# Hyperparameter search
# ---------------------------------------------------------------------------

def _random_search(
    chunks: List[Dict],
    embeddings: np.ndarray,
    n_iterations: int = HP_SEARCH_ITERATIONS,
    min_clusters: int = HP_MIN_CLUSTERS,
) -> Dict:
    """
    Rastgele hyperparameter arama. En yüksek (DBCV + LLM) / 2 skoruna sahip
    parametreleri döndür.

    Args:
        chunks     : [{text, ...}] listesi
        embeddings : (N, D) float array
        n_iterations: Deneme sayısı
        min_clusters: Bu sayının altında cluster üretirse geçerli sayılmaz

    Returns:
        best_params dict: {n_neighbors, min_cluster_size, min_samples,
                           epsilon, label_count, dbcv, llm_score, final_score}
    """
    best_result = None
    best_score = -1.0

    for i in range(n_iterations):
        n_neighbors = random.randint(*HP_N_NEIGHBORS_RANGE)
        min_cluster_size = random.randint(*HP_MIN_CLUSTER_SIZE_RANGE)
        min_samples = random.randint(*HP_MIN_SAMPLES_RANGE)
        epsilon = random.choice(HP_EPSILON_OPTIONS)

        try:
            umap_embs = _umap_reduce(embeddings, n_neighbors)
            clusterer = _hdbscan_fit(umap_embs, min_cluster_size, min_samples, epsilon)
            label_count, dbcv = _dbcv_score(clusterer)
        except Exception as exc:
            logger.debug("Clustering error (iter %d): %s", i, exc)
            continue

        if label_count < min_clusters:
            logger.debug(
                "Iter %d: %d cluster (< %d min) — atlandı",
                i, label_count, min_clusters,
            )
            continue

        llm_score = _evaluate_all_clusters_llm(chunks, clusterer.labels_)
        final_score = (dbcv + llm_score) / 2.0

        logger.info(
            "Iter %d: clusters=%d  dbcv=%.3f  llm=%.3f  final=%.3f",
            i, label_count, dbcv, llm_score, final_score,
        )

        if final_score > best_score:
            best_score = final_score
            best_result = {
                "n_neighbors": n_neighbors,
                "min_cluster_size": min_cluster_size,
                "min_samples": min_samples,
                "epsilon": epsilon,
                "label_count": label_count,
                "dbcv": dbcv,
                "llm_score": llm_score,
                "final_score": final_score,
                "labels": clusterer.labels_.tolist(),
            }

    if best_result is None:
        if min_clusters > 2:
            # İlk tur başarısız — daha gevşek parametreyle bir kez daha dene
            logger.warning(
                "Geçerli cluster bulunamadı (min=%d). min_clusters=2 ile tekrar deneniyor.",
                min_clusters,
            )
            return _random_search(chunks, embeddings, n_iterations, min_clusters=2)
        else:
            # HDBSCAN tamamen başarısız — KMeans fallback (k=5)
            logger.warning(
                "HDBSCAN hiç cluster üretemedi. KMeans (k=5) fallback kullanılıyor."
            )
            return _kmeans_fallback(chunks, embeddings, k=5)

    return best_result


def _kmeans_fallback(chunks: List[Dict], embeddings: np.ndarray, k: int = 5) -> Dict:
    """
    HDBSCAN tamamen başarısız olduğunda sklearn KMeans ile basit kümeleme.
    UMAP ile 10 boyuta indirgeriz, sonra KMeans uygularız.
    """
    from sklearn.cluster import KMeans
    try:
        reduced = _umap_reduce(embeddings, n_neighbors=min(15, len(chunks) - 1))
    except Exception:
        reduced = embeddings  # UMAP da başarısız olursa ham embedding kullan

    k_actual = min(k, len(chunks))
    km = KMeans(n_clusters=k_actual, random_state=42, n_init=10)
    labels = km.fit_predict(reduced)
    return {
        "n_neighbors": 15,
        "min_cluster_size": 3,
        "min_samples": 1,
        "epsilon": 0.0,
        "label_count": k_actual,
        "dbcv": 0.0,
        "llm_score": 0.5,
        "final_score": 0.5,
        "labels": labels.tolist(),
    }


# ---------------------------------------------------------------------------
# LLM: Cluster başlığı üretimi
# ---------------------------------------------------------------------------

_HEADLINE_SYSTEM = (
    "You are an expert summarizer for humanitarian situation reports. "
    "Respond ONLY with the title, nothing else."
)

_HEADLINE_USER_TEMPLATE = """\
The following passages are from a cluster of humanitarian documents.
Produce a short title (max 10 words) that best describes the main topic of this cluster.
Only return the title.

Passages:
{passages}
"""


def _generate_cluster_headline(paragraphs: List[str]) -> str:
    """Cluster başlığı üret."""
    sample = paragraphs[:5]
    passages_str = "\n---\n".join(f"[{i+1}] {p[:250]}" for i, p in enumerate(sample))
    prompt = _HEADLINE_USER_TEMPLATE.format(passages=passages_str)

    try:
        headline = llm_client.chat_simple(
            user_prompt=prompt,
            system_prompt=_HEADLINE_SYSTEM,
            max_tokens=LLM_MAX_TOKENS_HEADLINE,
        )
        # Tırnak işaretlerini temizle
        return headline.strip().strip('"').strip("'")
    except Exception as exc:
        logger.warning("Title generation failed: %s", exc)
        return "Unnamed Cluster"


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def run_clustering(
    chunks: List[Dict],
    n_iterations: Optional[int] = None,
    min_clusters: int = HP_MIN_CLUSTERS,
) -> Dict:
    """
    Chunk listesinden cluster'lar üretir.

    Args:
        chunks      : chroma_adapter'dan gelen [{id, text, embedding?, ...}]
        n_iterations: Hyperparameter arama iterasyon sayısı (None → config değeri)
        min_clusters: Minimum cluster sayısı

    Returns:
        {
          "0": {
            "cluster_articles": [{"id": "...", "text": "..."}],
            "cluster_headline": "...",
            "metadata": [{"title": "...", "url": "...", "source": "...", "date": "..."}]
          },
          ...
        }
    """
    if not chunks:
        raise ValueError("Chunk listesi boş — clustering yapılamaz.")

    n_iter = n_iterations or HP_SEARCH_ITERATIONS

    # 1. Embedding'leri al (Chroma'dan geliyorsa "embedding" anahtarında)
    embeddings_list = [c.get("embedding") for c in chunks]
    embeddings_list = [e for e in embeddings_list if e is not None]

    if len(embeddings_list) != len(chunks):
        raise ValueError(
            f"Bazı chunk'larda embedding yok. "
            f"({len(embeddings_list)}/{len(chunks)} embedding mevcut.) "
            "chroma_adapter.get_chunks_by_country() çağrısında "
            "include=['embeddings'] olduğundan emin olun."
        )

    embeddings = np.array(embeddings_list, dtype=float)
    logger.info("Clustering starting: %d chunks, %d dimensions", len(chunks), embeddings.shape[1])

    # 2. Hyperparameter search
    best = _random_search(chunks, embeddings, n_iter, min_clusters)
    labels = np.array(best["labels"])

    logger.info(
        "En iyi parametreler: n_neighbors=%d, min_cluster_size=%d, "
        "min_samples=%d, epsilon=%.2f → %d cluster, skor=%.3f",
        best["n_neighbors"], best["min_cluster_size"],
        best["min_samples"], best["epsilon"],
        best["label_count"], best["final_score"],
    )

    # 3. Cluster sözlüğünü oluştur
    unique_labels = sorted([l for l in set(labels) if l != -1])
    result: Dict = {}

    for label in unique_labels:
        indices = [i for i, lbl in enumerate(labels) if lbl == label]
        cluster_chunks = [chunks[i] for i in indices]
        texts = [c["text"] for c in cluster_chunks]

        # Başlık üret
        headline = _generate_cluster_headline(texts)

        # Metadata deduplication (aynı rapor birden fazla chunk içeriyor olabilir)
        seen_titles: set = set()
        metadata = []
        for c in cluster_chunks:
            if c["title"] not in seen_titles:
                seen_titles.add(c["title"])
                metadata.append({
                    "title": c["title"],
                    "url": c["url"],
                    "source": c["source"],
                    "date": c["date"],
                })

        result[str(label)] = {
            "cluster_articles": [
                {
                    "id": c["id"],
                    "text": c["text"],
                    "title": c.get("title", ""),
                    "url": c.get("url", ""),
                    "source": c.get("source", ""),
                    "date": c.get("date", ""),
                    "embedding": c.get("embedding"),
                }
                for c in cluster_chunks
            ],
            "cluster_headline": headline,
            "metadata": metadata,
        }

    logger.info("Clustering complete: %d clusters generated.", len(result))
    return result
