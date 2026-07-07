"""
sitrep_pipeline/rag_answers.py
Answer generation with RAG Fusion.

Original Stage 3 (3-RAG-GeneratedQuestions.ipynb) logic:
- ColBERT → replaced with Chroma .query()
- Sub-query generation + Reciprocal Rank Fusion (RRF k=60) preserved
- Answer synthesis prompt preserved verbatim (inline [n] citation)
"""

import json as _json
import logging
import os as _os

import llm_client

from config import (
    LLM_MAX_TOKENS_ANSWER,
    LLM_MODEL_ANSWERS,
    LLM_TEMPERATURE_ANSWERS,
    MAX_TOTAL_QUESTIONS,
    RETRIEVAL_TOP_K,
    RRF_K,
    RRF_NUM_SUBQUERIES,
)

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


def _generate_subqueries(question: str, n: int = RRF_NUM_SUBQUERIES) -> list[str]:
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
    ranked_lists: list[list[dict]],
    k: int = RRF_K,
) -> list[dict]:
    """
    Merges multiple ranked result lists using RRF.

    Args:
        ranked_lists: Each element is a result list; each result {"id": str, "text": str, ...}
        k: RRF constant (default 60)

    Returns:
        Chunk list sorted by RRF score.
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, dict] = {}

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


def _format_context(chunks: list[dict]) -> str:
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
    filtered_questions: dict,
    clusters: dict,
    chroma_adapter,
    country: str,
    hdx_context: dict | None = None,
    checkpoint_dir: str | None = None,
) -> list[dict]:
    """
    Answers filtered questions using Chroma RAG Fusion.

    Args:
        filtered_questions: Output of question_filtering.filter_questions()
                            {cluster_id: {cluster_headline, filtered_questions}}
        clusters          : Output of clustering.run_clustering()
                            {cluster_id: {cluster_articles, cluster_headline, metadata}}
        chroma_adapter    : ChromaAdapter instance
        country           : Country name for retrieval filter
        hdx_context       : Optional HDX enrichment data
        checkpoint_dir    : Directory for per-cluster checkpoint files (enables resume)

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
    all_answers: list[dict] = []

    # Work on a copy so the caller's filtered_questions dict is not mutated in place.
    # Mutating in place causes checkpoint/resume corruption: on restart the already-truncated
    # list gets truncated again, yielding fewer questions than intended.
    filtered_questions = {cid: dict(cd) for cid, cd in filtered_questions.items()}
    for cd in filtered_questions.values():
        cd["filtered_questions"] = list(cd.get("filtered_questions", []))

    # --- Dynamic question budget: distribute MAX_TOTAL_QUESTIONS proportionally ---
    total_questions = sum(
        len(cd.get("filtered_questions", []))
        for cd in filtered_questions.values()
    )
    num_clusters = len(filtered_questions)

    if total_questions > MAX_TOTAL_QUESTIONS:
        # Calculate per-cluster budget based on cluster size
        # Larger clusters get proportionally more questions
        cluster_sizes = {
            cid: len(cd.get("filtered_questions", []))
            for cid, cd in filtered_questions.items()
        }
        total_size = sum(cluster_sizes.values())

        # Distribute budget proportionally, with minimum 1 question per cluster
        remaining = MAX_TOTAL_QUESTIONS
        for cid, cd in filtered_questions.items():
            if remaining <= 0:
                cd["filtered_questions"] = []
                continue
            # Proportional share: (cluster_size / total_size) * budget
            share = max(1, round(cluster_sizes[cid] / total_size * MAX_TOTAL_QUESTIONS))
            take = min(len(cd.get("filtered_questions", [])), share, remaining)
            cd["filtered_questions"] = cd["filtered_questions"][:take]
            remaining -= take

        actual_total = sum(
            len(cd.get("filtered_questions", []))
            for cd in filtered_questions.values()
        )
        logger.info(
            "Dynamic budget: %d clusters, %d→%d questions (budget=%d, ~%.1f per cluster)",
            num_clusters, total_questions, actual_total, MAX_TOTAL_QUESTIONS,
            MAX_TOTAL_QUESTIONS / max(1, num_clusters),
        )

    # --- Resume from checkpoint if available ---
    completed_clusters: set = set()
    if checkpoint_dir:
        _os.makedirs(checkpoint_dir, exist_ok=True)
        cp_file = _os.path.join(checkpoint_dir, "answers_progress.json")
        if _os.path.exists(cp_file):
            try:
                with open(cp_file, encoding="utf-8") as f:
                    progress = _json.load(f)
                completed_clusters = set(progress.get("completed_clusters", []))
                # Load previously saved answers
                for cid in completed_clusters:
                    cluster_cp = _os.path.join(checkpoint_dir, f"answers_{cid}.json")
                    if _os.path.exists(cluster_cp):
                        with open(cluster_cp, encoding="utf-8") as f:
                            all_answers.extend(_json.load(f))
                logger.info(
                    "Resumed from checkpoint: %d clusters already done, %d answers loaded.",
                    len(completed_clusters), len(all_answers),
                )
            except Exception as exc:
                logger.warning("Failed to load checkpoint, starting fresh: %s", exc)
                all_answers = []
                completed_clusters = set()

    for cluster_id, cluster_data in filtered_questions.items():
        # Skip already completed clusters (resume support)
        if cluster_id in completed_clusters:
            logger.info("Cluster %s: already completed, skipping.", cluster_id)
            continue

        questions = cluster_data.get("filtered_questions", [])
        cluster_chunks = clusters.get(cluster_id, {}).get("cluster_articles", [])

        logger.info(
            "Cluster %s: Answering %d questions (%d chunks in pool)",
            cluster_id, len(questions), len(cluster_chunks),
        )

        cluster_answers: list[dict] = []

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
            ranked_lists: list[list[dict]] = []
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
                cluster_answers.append({
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

            cluster_answers.append({
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

        # --- Per-cluster checkpoint ---
        if checkpoint_dir:
            cluster_cp = _os.path.join(checkpoint_dir, f"answers_{cluster_id}.json")
            try:
                with open(cluster_cp, "w", encoding="utf-8") as f:
                    _json.dump(cluster_answers, f, ensure_ascii=False, indent=2)
                # Update progress file
                completed_clusters.add(cluster_id)
                progress = {"completed_clusters": sorted(completed_clusters)}
                with open(_os.path.join(checkpoint_dir, "answers_progress.json"), "w", encoding="utf-8") as f:
                    _json.dump(progress, f)
                logger.info("  Checkpoint saved for cluster %s (%d answers).", cluster_id, len(cluster_answers))
            except Exception as exc:
                logger.warning("  Failed to save checkpoint for cluster %s: %s", cluster_id, exc)

        all_answers.extend(cluster_answers)

    logger.info("%d questions answered in total.", len(all_answers))
    return all_answers
