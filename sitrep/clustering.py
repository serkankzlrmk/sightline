"""
sitrep_pipeline/clustering.py
Separates chunks into topic clusters and generates a headline for each cluster.

Based on original Stage 1 (1-clean-clustering.ipynb) logic but:
- Paragraph creation step skipped (Chroma chunks are already ready)
- Embeddings are pulled from Chroma (no local model needed)
- LLM calls are made via OpenRouter
"""

import logging
import random
import re

import llm_client
import numpy as np

from config import (
    HDBSCAN_CLUSTER_SELECTION_METHOD,
    HDBSCAN_METRIC,
    HP_EPSILON_OPTIONS,
    HP_MIN_CLUSTER_SIZE_RANGE,
    HP_MIN_CLUSTERS,
    HP_MIN_SAMPLES_RANGE,
    HP_N_NEIGHBORS_RANGE,
    HP_SEARCH_ITERATIONS,
    LLM_MAX_TOKENS_HEADLINE,
    UMAP_METRIC,
    UMAP_MIN_DIST,
    UMAP_N_COMPONENTS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding → UMAP → HDBSCAN
# ---------------------------------------------------------------------------

def _umap_reduce(embeddings: np.ndarray, n_neighbors: int) -> np.ndarray:
    """UMAP dimensionality reduction."""
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
    """Create and fit HDBSCAN cluster object."""
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


def _dbcv_score(clusterer, prob_threshold: float = 0.05) -> tuple[int, float]:
    """
    Returns (label_count, dbcv_score).
    Noise (-1) labels are not counted.
    """
    labels = clusterer.labels_
    # Count points below a confidence threshold as noise
    labels = np.where(clusterer.probabilities_ >= prob_threshold, labels, -1)
    label_count = len(set(labels)) - (1 if -1 in labels else 0)
    dbcv = float(clusterer.relative_validity_)
    return label_count, dbcv


# ---------------------------------------------------------------------------
# LLM: Cluster quality evaluation
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


def _llm_coherence_score(paragraphs: list[str]) -> float:
    """
    Returns average LLM coherence + homogeneity score for given paragraphs.
    Returns 0.5 if parsing fails.
    """
    sample = paragraphs[:8]  # Send max 8 paragraphs to LLM (token savings)
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
    chunks: list[dict], labels: np.ndarray
) -> float:
    """
    Average LLM coherence score for all clusters.
    Each cluster is evaluated by sampling up to 6 chunks.
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


def _adaptive_ranges(n_chunks: int):
    """Select HDBSCAN hyperparameter ranges based on data size."""
    if n_chunks < 50:
        return (3, 15), (1, 5), (3, min(15, n_chunks - 1))
    elif n_chunks < 200:
        return (5, 30), (1, 8), (5, min(25, n_chunks - 1))
    elif n_chunks < 500:
        return (8, 50), (1, 10), (5, 30)
    else:
        return HP_MIN_CLUSTER_SIZE_RANGE, HP_MIN_SAMPLES_RANGE, HP_N_NEIGHBORS_RANGE


def _random_search(
    chunks: list[dict],
    embeddings: np.ndarray,
    n_iterations: int = HP_SEARCH_ITERATIONS,
    min_clusters: int = HP_MIN_CLUSTERS,
) -> dict:
    """
    Random hyperparameter search.
    1) Find candidates by collecting DBCV scores via UMAP+HDBSCAN
    2) Evaluate top 3 candidates with LLM coherence
    3) Return the highest (DBCV + LLM) / 2 score
    """
    n_chunks = len(chunks)
    mcs_range, ms_range, nn_range = _adaptive_ranges(n_chunks)

    logger.info(
        "Adaptive HP ranges for %d chunks: mcs=%s, ms=%s, nn=%s",
        n_chunks, mcs_range, ms_range, nn_range,
    )

    # Phase 1: Collect DBCV-only candidates (fast, no LLM)
    candidates = []

    for i in range(n_iterations):
        n_neighbors = random.randint(*nn_range)
        min_cluster_size = random.randint(*mcs_range)
        min_samples = random.randint(*ms_range)
        epsilon = random.choice(HP_EPSILON_OPTIONS)

        # UMAP hard constraint
        n_neighbors = min(n_neighbors, max(2, n_chunks - 1))

        try:
            umap_embs = _umap_reduce(embeddings, n_neighbors)
            clusterer = _hdbscan_fit(umap_embs, min_cluster_size, min_samples, epsilon)
            label_count, dbcv = _dbcv_score(clusterer)
        except Exception as exc:
            logger.debug("Clustering error (iter %d): %s", i, exc)
            continue

        if label_count < min_clusters:
            logger.debug(
                "Iter %d: %d clusters (< %d min) — skipped",
                i, label_count, min_clusters,
            )
            continue

        logger.info(
            "Iter %d: clusters=%d  dbcv=%.3f  params=(nn=%d, mcs=%d, ms=%d, eps=%.2f)",
            i, label_count, dbcv, n_neighbors, min_cluster_size, min_samples, epsilon,
        )

        candidates.append({
            "n_neighbors": n_neighbors,
            "min_cluster_size": min_cluster_size,
            "min_samples": min_samples,
            "epsilon": epsilon,
            "label_count": label_count,
            "dbcv": dbcv,
            "labels": clusterer.labels_.tolist(),
        })

    if not candidates:
        if min_clusters > 2:
            logger.warning(
                "No valid clusters found (min=%d). Retrying with min_clusters=2.",
                min_clusters,
            )
            return _random_search(chunks, embeddings, n_iterations, min_clusters=2)
        else:
            logger.warning(
                "HDBSCAN failed to produce any clusters. Using KMeans fallback."
            )
            return _kmeans_fallback(chunks, embeddings)

    # Phase 2: Sort by DBCV, evaluate only top-3 with LLM (saves ~90% LLM calls)
    candidates.sort(key=lambda c: c["dbcv"], reverse=True)
    top_n = candidates[:3]

    best_result = None
    best_score = -1.0

    for cand in top_n:
        llm_score = _evaluate_all_clusters_llm(chunks, np.array(cand["labels"]))
        cand["llm_score"] = llm_score
        cand["final_score"] = (cand["dbcv"] + llm_score) / 2.0

        logger.info(
            "Top candidate: clusters=%d  dbcv=%.3f  llm=%.3f  final=%.3f",
            cand["label_count"], cand["dbcv"], llm_score, cand["final_score"],
        )

        if cand["final_score"] > best_score:
            best_score = cand["final_score"]
            best_result = cand

    return best_result


def _kmeans_fallback(chunks: list[dict], embeddings: np.ndarray, k: int | None = None) -> dict:
    """
    Simple clustering with sklearn KMeans when HDBSCAN fails completely.
    If k is not provided, it is auto-selected based on data size: sqrt(n/10), min 2, max 12.
    """
    from sklearn.cluster import KMeans
    n = len(chunks)

    if k is None:
        k = max(2, min(12, int(np.sqrt(n / 10))))

    logger.info("KMeans fallback: %d chunks -> k=%d", n, k)

    try:
        nn = min(15, max(2, n - 1))
        reduced = _umap_reduce(embeddings, n_neighbors=nn)
    except Exception:
        reduced = embeddings  # If UMAP also fails, use raw embeddings

    k_actual = min(k, n)
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
# LLM: Cluster headline generation
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


def _generate_cluster_headline(paragraphs: list[str]) -> str:
    """Generate cluster headline."""
    sample = paragraphs[:5]
    passages_str = "\n---\n".join(f"[{i+1}] {p[:250]}" for i, p in enumerate(sample))
    prompt = _HEADLINE_USER_TEMPLATE.format(passages=passages_str)

    try:
        headline = llm_client.chat_simple(
            user_prompt=prompt,
            system_prompt=_HEADLINE_SYSTEM,
            max_tokens=LLM_MAX_TOKENS_HEADLINE,
        )
        # Clean up quotation marks
        return headline.strip().strip('"').strip("'")
    except Exception as exc:
        logger.warning("Title generation failed: %s", exc)
        return "Unnamed Cluster"


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def run_clustering(
    chunks: list[dict],
    n_iterations: int | None = None,
    min_clusters: int = HP_MIN_CLUSTERS,
) -> dict:
    """
    Generates clusters from a chunk list.

    Args:
        chunks      : [{id, text, embedding?, ...}] from chroma_adapter
        n_iterations: Number of hyperparameter search iterations (None → config value)
        min_clusters: Minimum number of clusters

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
        raise ValueError("Chunk list is empty — cannot perform clustering.")

    n_iter = n_iterations or HP_SEARCH_ITERATIONS

    # 1. Get embeddings (from Chroma/pgvector via "embedding" key)
    embeddings_list = [c.get("embedding") for c in chunks]

    # Normalise embeddings: handle string format from pgvector/psycopg2
    import json as _json
    parsed = []
    for i, e in enumerate(embeddings_list):
        if e is None:
            raise ValueError(
                f"Chunk {i} (id={chunks[i].get('id', '?')}) is missing an embedding. "
                "Ensure include=['embeddings'] is set in the data source call."
            )
        if isinstance(e, str):
            # pgvector/psycopg2 may return embeddings as strings like '[-0.07,0.05,...]'
            try:
                parsed.append(_json.loads(e))
            except (ValueError, _json.JSONDecodeError):
                # Fallback: strip brackets and split
                stripped = e.strip()
                if stripped.startswith('[') and stripped.endswith(']'):
                    stripped = stripped[1:-1]
                parsed.append([float(x) for x in stripped.split(',') if x.strip()])
        elif isinstance(e, np.ndarray):
            parsed.append(e.tolist())
        elif isinstance(e, list):
            parsed.append(e)
        else:
            # Last resort: try numpy conversion
            try:
                parsed.append(np.array(e).tolist())
            except Exception:
                raise ValueError(
                    f"Chunk {i} has an unparseable embedding of type {type(e).__name__}. "
                    "Cannot convert to float list."
                )

    embeddings = np.array(parsed, dtype=float)
    logger.info("Clustering starting: %d chunks, %d dimensions", len(chunks), embeddings.shape[1])

    # 2. Hyperparameter search
    best = _random_search(chunks, embeddings, n_iter, min_clusters)
    labels = np.array(best["labels"])

    logger.info(
        "Best parameters: n_neighbors=%d, min_cluster_size=%d, "
        "min_samples=%d, epsilon=%.2f → %d clusters, score=%.3f",
        best["n_neighbors"], best["min_cluster_size"],
        best["min_samples"], best["epsilon"],
        best["label_count"], best["final_score"],
    )

    # 3. Build cluster dictionary
    unique_labels = sorted([l for l in set(labels) if l != -1])
    result: dict = {}

    for label in unique_labels:
        indices = [i for i, lbl in enumerate(labels) if lbl == label]
        cluster_chunks = [chunks[i] for i in indices]
        texts = [c["text"] for c in cluster_chunks]

        # Generate headline
        headline = _generate_cluster_headline(texts)

        # Metadata deduplication (same report may have multiple chunks)
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
