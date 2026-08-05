"""
sitrep_pipeline/citation_postprocess.py
Citation validation and re-ranking.

Original Stage 3.1 (3.1-RAG_PostProcessingCitations.ipynb) logic:
- For each citation, compute Jaccard + Cosine (query-doc) combined score against source text
- Replace citations below threshold with the best match
- mu=0.8 (Jaccard weight), threshold=0.3

Note: DefaultEmbeddingFunction is used for cosine computation
     (instead of modernbert — compatible with Chroma)
"""

import logging
import re

import numpy as np

logger = logging.getLogger(__name__)

# Constants from original
MU: float = 0.8  # Jaccard weight
THRESHOLD: float = 0.3  # Minimum combined score

# Threshold to prevent forced assignment when match is meaningless
# If no document even exceeds FORCE_THRESHOLD, original citations are preserved.
# (Protection for acronym lists, index documents, and other irrelevant docs)
FORCE_THRESHOLD: float = 0.10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jaccard_similarity(text1: str, text2: str) -> float:
    """Word-level Jaccard similarity."""
    if not text1 or not text2:
        return 0.0
    set1 = set(text1.lower().split())
    set2 = set(text2.lower().split())
    intersection = set1 & set2
    union = set1 | set2
    return len(intersection) / len(union) if union else 0.0


def _get_embeddings(texts: list[str]) -> np.ndarray:
    """Compute embeddings using DefaultEmbeddingFunction."""
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    ef = DefaultEmbeddingFunction()
    embs = ef(texts)
    return np.array(embs, dtype=float)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def _update_single_answer(answer: dict) -> dict:
    """
    Updates citations for a single question-answer pair.

    Input:
        {
          "retrieved_answer": "text [1][3] more text [2]",
          "retrieved_contexts": ["doc1", "doc2", "doc3", ...],
          "question": str,
          ...
        }

    Output (original keys + new keys together):
        {
          ...,  # original fields
          "updated_retrieved_answer": "text [2][3] more text [1]",
          "new_citations": [1, 2, 3],
          "new_used_contexts": ["doc...", ...],
          "old_citations": [1, 2, 3],
          "old_used_contexts": ["doc...", ...],
        }
    """
    answer = dict(answer)  # copy
    question = answer.get("question", "")
    response = answer.get("retrieved_answer", "")
    retrieved_docs: list[str] = answer.get("retrieved_contexts", [])
    retrieved_metas: list[dict] = answer.get("retrieved_contexts_meta", [])

    # If no citations, skip
    if "[" not in response or not retrieved_docs:
        answer["updated_retrieved_answer"] = response
        answer["new_citations"] = []
        answer["new_used_contexts"] = []
        answer["new_used_contexts_meta"] = []
        answer["old_citations"] = []
        answer["old_used_contexts"] = []
        return answer

    # Extract original citations
    old_citation_numbers = sorted(
        {int(m) for m in re.findall(r"\[(\d+)\]", response) if 0 < int(m) <= len(retrieved_docs)}
    )
    old_used_contexts = [retrieved_docs[i - 1] for i in old_citation_numbers if 0 < i <= len(retrieved_docs)]

    # Compute embeddings: question + all documents
    try:
        all_texts = [question] + retrieved_docs
        all_embs = _get_embeddings(all_texts)
        query_emb = all_embs[0]
        doc_embs = all_embs[1:]
        cosine_scores = np.array([_cosine_sim(query_emb, d) for d in doc_embs])
    except Exception as exc:
        logger.warning("Embedding error, skipping citation post-processing: %s", exc)
        answer["updated_retrieved_answer"] = response
        answer["new_citations"] = old_citation_numbers
        answer["new_used_contexts"] = old_used_contexts
        answer["new_used_contexts_meta"] = [
            retrieved_metas[i - 1] if 0 < i <= len(retrieved_metas) else {}
            for i in old_citation_numbers
            if 0 < i <= len(retrieved_docs)
        ]
        answer["old_citations"] = old_citation_numbers
        answer["old_used_contexts"] = old_used_contexts
        return answer

    # Find each "text_piece [n][m]..." pattern and re-evaluate
    pattern = re.compile(r"(.*?)((?:\[\d+\])+)", re.DOTALL)
    updated_response = response
    all_new_citation_indices: set[int] = set()
    current_offset = 0

    for match in pattern.finditer(response):
        text_piece = match.group(1).strip()
        citation_str = match.group(2)

        orig_indices = [int(n) for n in re.findall(r"\d+", citation_str)]
        k = len(orig_indices)

        new_markers = ""
        new_valid_indices: list[int] = []

        if k > 0 and cosine_scores.size > 0:
            piece_scores: list[tuple[float, int]] = []
            for j, doc_text in enumerate(retrieved_docs):
                jac = _jaccard_similarity(text_piece, doc_text)
                cos = float(cosine_scores[j])
                combined = MU * jac + (1 - MU) * cos
                piece_scores.append((combined, j + 1))  # 1-indexed

            piece_scores.sort(reverse=True, key=lambda x: x[0])
            top_k = piece_scores[:k]

            new_valid_indices = [idx for score, idx in top_k if score >= THRESHOLD]
            if not new_valid_indices and top_k:
                # No document exceeded THRESHOLD.
                # If the best document exceeds FORCE_THRESHOLD, use it;
                # otherwise preserve original citations (acronym list / irrelevant doc protection)
                best_score, best_idx = top_k[0]
                if best_score >= FORCE_THRESHOLD:
                    new_valid_indices = [best_idx]
                else:
                    new_valid_indices = [idx for idx in orig_indices if 0 < idx <= len(retrieved_docs)]

            new_valid_indices.sort()
            new_markers = "".join(f"[{idx}]" for idx in new_valid_indices)

        all_new_citation_indices.update(new_valid_indices)

        replacement = text_piece + new_markers
        start = match.start() + current_offset
        end = match.end() + current_offset
        updated_response = updated_response[:start] + replacement + updated_response[end:]
        current_offset += len(replacement) - (match.end() - match.start())

    final_citations = sorted(all_new_citation_indices)
    new_used_contexts = [retrieved_docs[i - 1] for i in final_citations if 0 < i <= len(retrieved_docs)]
    new_used_contexts_meta = [
        retrieved_metas[i - 1] if 0 < i <= len(retrieved_metas) else {}
        for i in final_citations
        if 0 < i <= len(retrieved_docs)
    ]

    answer["updated_retrieved_answer"] = updated_response
    answer["new_citations"] = final_citations
    answer["new_used_contexts"] = new_used_contexts
    answer["new_used_contexts_meta"] = new_used_contexts_meta
    answer["old_citations"] = old_citation_numbers
    answer["old_used_contexts"] = old_used_contexts
    return answer


def postprocess_citations(answers: list[dict]) -> list[dict]:
    """
    Applies citation post-processing to all answers.

    Args:
        answers: Output of rag_answers.answer_questions()

    Returns:
        Each item has updated_retrieved_answer, new_citations,
        new_used_contexts, old_citations, old_used_contexts added.
    """
    updated: list[dict] = []
    changed = 0

    for i, answer in enumerate(answers):
        try:
            result = _update_single_answer(answer)
            if set(result.get("new_citations", [])) != set(result.get("old_citations", [])):
                changed += 1
        except Exception as exc:
            logger.error("Citation post-processing failed for answer %d: %s", i, exc)
            result = dict(answer)
            result.setdefault("updated_retrieved_answer", answer.get("retrieved_answer", ""))
            result.setdefault("new_citations", [])
            result.setdefault("new_used_contexts", [])
            result.setdefault("old_citations", [])
            result.setdefault("old_used_contexts", [])

        updated.append(result)

    logger.info(
        "Citation post-processing complete: %d/%d answers updated.",
        changed,
        len(answers),
    )
    return updated
