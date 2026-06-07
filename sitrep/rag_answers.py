"""
sitrep_pipeline/rag_answers.py
Answer generation with RAG Fusion.

Original Stage 3 (3-RAG-GeneratedQuestions.ipynb) logic:
- ColBERT → replaced with Chroma .query()
- Sub-query generation + Reciprocal Rank Fusion (RRF k=60) preserved
- Answer synthesis prompt preserved verbatim (inline [n] citation)
"""

import re
import logging
from typing import List, Dict, Optional, Tuple

from config import (
    RETRIEVAL_TOP_K,
    RRF_K,
    RRF_NUM_SUBQUERIES,
    LLM_MAX_TOKENS_ANSWER,
    LLM_MODEL_ANSWERS,
    LLM_TEMPERATURE_ANSWERS,
)
import llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-query generation
# ---------------------------------------------------------------------------

_SUBQUERY_SYSTEM = (
    "You are a helpful assistant that generates multiple search queries based on a single input query."
)

_SUBQUERY_USER_TEMPLATE = (
    "Generate {n} different search queries related to the following question. "
    "Each query should approach the topic from a slightly different angle to improve retrieval coverage. "
    "Output ONLY the queries, one per line, with no numbering or extra text.\n\n"
    "Question: {question}"
)


def _generate_subqueries(question: str, n: int = RRF_NUM_SUBQUERIES) -> List[str]:
    """
    Generates n sub-queries from different angles based on the main question (for RAG Fusion).
    """
    prompt = _SUBQUERY_USER_TEMPLATE.format(n=n, question=question)
    try:
        raw = llm_client.chat_simple(
            user_prompt=prompt,
            system_prompt=_SUBQUERY_SYSTEM,
            max_tokens=256,
        )
        queries = [q.strip() for q in raw.strip().splitlines() if q.strip()]
        # Also include the original question
        queries = [question] + queries[:n]
        return queries
    except Exception as exc:
        logger.warning("Sub-query generation failed: %s — using original question only.", exc)
        return [question]


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

def _reciprocal_rank_fusion(
    ranked_lists: List[List[Dict]],
    k: int = RRF_K,
) -> List[Dict]:
    """
    Merges multiple ranked result lists using RRF.

    Args:
        ranked_lists: Each element is a result list; each result {"id": str, "text": str, ...}
        k: RRF constant (default 60)

    Returns:
        Chunk list sorted by RRF score.
    """
    scores: Dict[str, float] = {}
    chunk_map: Dict[str, Dict] = {}

    for result_list in ranked_lists:
        for rank, chunk in enumerate(result_list, start=1):
            cid = chunk.get("id", chunk.get("text", "")[:50])
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in chunk_map:
                chunk_map[cid] = chunk

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return [chunk_map[cid] for cid in sorted_ids]


# ---------------------------------------------------------------------------
# Answer generation prompt (verbatim from original)
# ---------------------------------------------------------------------------

_ANSWER_TEMPLATE = """\
**Role:** You are an expert AI assistant specializing in answering questions *strictly* from provided source documents. Your primary directive is to provide accurate, concise answers, meticulously citing every piece of information.

**Task:**
1.  Carefully analyze the numbered source documents provided in the "Context" section.
2.  Answer the user's "Query" *exclusively* using information found within these sources.
3.  Every factual statement, phrase, or piece of data in your answer MUST be supported by a citation.

**Instructions for Citation:**
* **Granular Citation:** Place citations `[Source Number]` immediately after the *specific sentence or clause* that the information comes from. Aim for the smallest possible unit of text that can be attributed.
* **Multiple Sources:** If a single piece of information is supported by content from multiple sources, list all relevant source numbers together without spaces, e.g., `[1][2][5]`.
* **No Source, No Statement:** If you cannot find direct support for a piece of information in the provided sources, **DO NOT include that information** in your answer.
* **Source Range:** Your citations *must* correspond to the provided source numbers (1, 2, 3... up to {n_sources}). Do not generate citation numbers outside this range.
* **Prioritize Directness:** If multiple sources provide the same information, prioritize the most direct and clear phrasing, and cite all relevant sources.

**Instructions for Answer Content:**
* **Conciseness & Precision:** Keep your answer as concise and direct as possible, while fully addressing the query. Avoid conversational fillers or unnecessary elaboration.
* **No Outside Knowledge:** Do NOT use any information, assumptions, or interpretations not explicitly stated in the provided sources. This is crucial for preventing hallucinations.
* **Handling Missing Information:**
    * If the provided sources contain *relevant* information but *do not definitively answer* the specific question, respond: `No clear answer.`
    * If *none* of the sources contain *any* information relevant to the query, respond: `The provided sources do not contain information relevant to this query.`

---

**Context:**
{context}

**Query:** {question}

**Answer:**
"""


def _format_context(chunks: List[Dict]) -> str:
    """Converts a chunk list to numbered source format."""
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        text = chunk.get("text", "").strip()
        lines.append(f"Source {i}: {text}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Main RAG function
# ---------------------------------------------------------------------------

def answer_questions(
    filtered_questions: Dict,
    clusters: Dict,
    chroma_adapter,
    country: str,
    hdx_context: Optional[Dict] = None,
) -> List[Dict]:
    """
    Answers filtered questions using Chroma RAG Fusion.

    Args:
        filtered_questions: Output of question_filtering.filter_questions()
                            {cluster_id: {cluster_headline, filtered_questions}}
        clusters          : Output of clustering.run_clustering()
                            {cluster_id: {cluster_articles, cluster_headline, metadata}}
        chroma_adapter    : ChromaAdapter instance
        country           : Country name for retrieval filter

    Returns:
        [
          {
            "cluster_id"      : str,
            "question"        : str,
            "retrieved_answer": str,   # contains "[n]" inline citations
            "retrieved_contexts": [str, ...],  # ordered source texts
          },
          ...
        ]
    """
    all_answers: List[Dict] = []

    for cluster_id, cluster_data in filtered_questions.items():
        questions = cluster_data.get("filtered_questions", [])
        cluster_chunks = clusters.get(cluster_id, {}).get("cluster_articles", [])

        logger.info(
            "Cluster %s: Answering %d questions (%d chunks in pool)",
            cluster_id, len(questions), len(cluster_chunks),
        )

        for question in questions:
            logger.debug("  Question: %s", question[:80])

            # 1. Generate sub-queries
            subqueries = _generate_subqueries(question)
            logger.debug("  %d sub-queries generated", len(subqueries))

            # 2. Retrieval for each sub-query (within cluster_chunks pool)
            # If pool chunks have embeddings, use pool-based retrieval; otherwise use global Chroma query
            pool_has_embeddings = bool(
                cluster_chunks and cluster_chunks[0].get("embedding") is not None
            )
            ranked_lists: List[List[Dict]] = []
            for sq in subqueries:
                if pool_has_embeddings:
                    results = chroma_adapter.retrieve(
                        query=sq,
                        country=country,
                        k=RETRIEVAL_TOP_K,
                        candidate_pool=cluster_chunks,
                    )
                else:
                    # If no embedding, use global country-filtered Chroma query
                    results = chroma_adapter.retrieve(
                        query=sq,
                        country=country,
                        k=RETRIEVAL_TOP_K,
                    )
                ranked_lists.append(results)

            # 3. Merge with RRF
            fused = _reciprocal_rank_fusion(ranked_lists, k=RRF_K)
            top_chunks = fused[:RETRIEVAL_TOP_K]

            if not top_chunks:
                logger.warning("  No chunks found for question: %s", question[:60])
                all_answers.append({
                    "cluster_id": cluster_id,
                    "question": question,
                    "retrieved_answer": "The provided sources do not contain information relevant to this query.",
                    "retrieved_contexts": [],
                })
                continue

            # 4. Answer synthesis
            context_str = _format_context(top_chunks)

            # Inject HDX quantitative data if available
            hdx_prefix = ""
            if hdx_context:
                try:
                    from hdx_enrichment import format_hdx_for_rag_context
                    hdx_text = format_hdx_for_rag_context(hdx_context)
                    if hdx_text:
                        hdx_prefix = hdx_text + "\n\n"
                except Exception as exc:
                    logger.warning("HDX enrichment for RAG context failed: %s", exc)

            answer_prompt = _ANSWER_TEMPLATE.format(
                n_sources=len(top_chunks),
                context=hdx_prefix + context_str,
                question=question,
            )

            try:
                answer = llm_client.chat_simple(
                    user_prompt=answer_prompt,
                    max_tokens=LLM_MAX_TOKENS_ANSWER,
                    model=LLM_MODEL_ANSWERS,
                    temperature=LLM_TEMPERATURE_ANSWERS,
                )
            except Exception as exc:
                logger.error("  Answer generation failed: %s", exc)
                answer = "No clear answer."

            all_answers.append({
                "cluster_id": cluster_id,
                "question": question,
                "retrieved_answer": answer.strip(),
                "retrieved_contexts": [c.get("text", "") for c in top_chunks],
                "retrieved_contexts_meta": [
                    {
                        "title": c.get("title", ""),
                        "url": c.get("url", ""),
                        "source": c.get("source", ""),
                        "date": c.get("date", ""),
                    }
                    for c in top_chunks
                ],
            })

            logger.debug("  Answer: %s", answer[:120])

    logger.info("%d questions answered in total.", len(all_answers))
    return all_answers
