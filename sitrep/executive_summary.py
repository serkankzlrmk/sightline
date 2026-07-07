"""
sitrep_pipeline/executive_summary.py
Generates an executive summary by collecting used contexts from all answers.

Version 2 changes:
- Added cluster_summaries parameter → generates from cluster summaries for SITREP format
- Citation metadata (title/url) now carried via cited_paragraphs_meta
- report_assembly.py fuzzy match fallback no longer needed
"""

import logging
import re
from itertools import zip_longest

import llm_client
from rag_answers import _generate_subqueries, _reciprocal_rank_fusion

from config import (
    LLM_MAX_TOKENS_SUMMARY,
    RETRIEVAL_TOP_K_SUMMARY,
    RRF_K,
)

logger = logging.getLogger(__name__)

_EXEC_SUMMARY_QUERY = "Generate a summary of the current situation."


# ---------------------------------------------------------------------------
# Prompt: SITREP executive summary from cluster summaries (preferred path)
# ---------------------------------------------------------------------------

_SITREP_SUMMARY_TEMPLATE = """\
You are an expert AI assistant specialized in writing executive summaries for humanitarian Situational Reports (SITREPs).

Your task is to produce a structured executive summary based **exclusively** on the numbered cluster summaries provided below.

**Structure your response in 2–4 paragraphs covering:**
1. **Overall Situation**: Key developments, conflict or crisis dynamics, affected areas and scale
2. **Humanitarian Needs**: Affected population, displacement, protection concerns, sector-specific needs (health, food, shelter, WASH, etc.)
3. **Response & Gaps**: Humanitarian response activities, funding status, access constraints, capacity gaps
4. *(If information is available)* **Priorities & Outlook**: Immediate priorities, emerging risks

**Rules:**
- Write in **prose only** — no headers, no bullet points, no numbered lists in the output.
- Cite every statement with `[N]` immediately after the relevant information, where N is the source number.
- If multiple sources support the same fact, combine citations like `[1][3]` with no space between them.
- Every paragraph **must** contain at least one citation.
- Do **not** introduce any information not present in the sources.
- Do not use citation numbers greater than the total number of sources provided.

---

**Sources:**
{context}

---

**Executive Summary:**
"""


# ---------------------------------------------------------------------------
# Prompt: Executive summary from raw chunks (fallback path)
# ---------------------------------------------------------------------------

_EXEC_SUMMARY_TEMPLATE = """\
You are an expert AI assistant specialized in writing executive summaries for humanitarian Situational Reports (SITREPs).

Carefully analyze the source documents provided in the context below. Then, generate a structured summary in 2–3 paragraphs that provides an overview of the humanitarian situation described in the documents.

**Structure:**
- Paragraph 1: Overall situation and key developments
- Paragraph 2: Humanitarian needs and affected populations
- Paragraph 3: Response activities and gaps (if information is available)

**Rules:**
- Write in **prose only** — no headers, no bullet points, no numbered lists in the output.
- Cite every statement with `[N]` immediately after the relevant information.
- Use `[1][2]` (no space) when multiple sources support the same claim.
- Every paragraph must contain at least one citation.
- Do **not** introduce any information not present in the sources.
- Citation numbers must correspond **accurately** to the sources provided.

---

**Context:**
{context}

---

**Executive Summary:**
"""


def _format_numbered_context(items: list[dict]) -> str:
    """
    Converts a [{"title": str, "text": str}, ...] list to numbered source format.
    If title is present, a title line is added.
    """
    parts = []
    for i, item in enumerate(items):
        title = item.get("title", "")
        text = item.get("text", "")
        if title:
            parts.append(f"Source {i+1}: [{title}]\n{text}")
        else:
            parts.append(f"Source {i+1}: {text}")
    return "\n\n".join(parts)


def _simple_retrieve(
    query: str,
    corpus: list[str],
    k: int,
) -> list[dict]:
    """
    Performs embedding-based retrieval over a corpus (string list).
    Uses simple cosine similarity instead of ColBERT for small pools.

    Returns:
        [{"id": str, "text": str, "rank": int, "similarity": float}]
    """
    if not corpus:
        return []

    try:
        import numpy as np
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        ef = DefaultEmbeddingFunction()
        all_texts = [query] + corpus
        all_embs = np.array(ef(all_texts), dtype=float)
        query_emb = all_embs[0]
        doc_embs = all_embs[1:]

        sims = []
        for i, doc_emb in enumerate(doc_embs):
            denom = np.linalg.norm(query_emb) * np.linalg.norm(doc_emb)
            sim = float(np.dot(query_emb, doc_emb) / denom) if denom > 0 else 0.0
            sims.append((sim, i))

        sims.sort(reverse=True, key=lambda x: x[0])
        top = sims[:k]

        return [
            {
                "id": str(idx),
                "text": corpus[idx],
                "rank": rank + 1,
                "similarity": round(sim, 3),
            }
            for rank, (sim, idx) in enumerate(top)
        ]
    except Exception as exc:
        logger.warning("Embedding-based retrieval failed, falling back to rank-based: %s", exc)
        return [
            {"id": str(i), "text": t, "rank": i + 1, "similarity": 0.0}
            for i, t in enumerate(corpus[:k])
        ]


def generate_executive_summary(
    postprocessed_answers: list[dict],
    cluster_summaries: dict | None = None,
    hdx_context: dict | None = None,
) -> dict:
    """
    Generates an executive summary.

    Preferred path (when cluster_summaries is provided):
        Each cluster headline + narrative summary is used as a source.
        Produces 2-4 paragraphs in SITREP format.

    Fallback path (when cluster_summaries is None):
        Performs RRF retrieval on all used contexts from answers.
        Generates summary from raw chunks.

    Args:
        postprocessed_answers: Output of citation_postprocess.postprocess_citations()
        cluster_summaries    : Output of cluster_summary.generate_cluster_summaries() (optional)

    Returns:
        {
          "summary"              : str,
          "cited_paragraphs"     : [str],
          "cited_paragraphs_meta": [{"title": str, "url": str}],  # parallel to cited_paragraphs
          "full_paragraphs"      : [str],
        }
    """

    # =========================================================================
    # PATH A: Generate in SITREP format from cluster summaries
    # =========================================================================
    if cluster_summaries:
        sources = []  # [{"cluster_id": str, "title": str, "text": str}]
        for cid, cdata in cluster_summaries.items():
            summary_text = cdata.get("summary", "").strip()
            title = cdata.get("title", f"Cluster {cid}")
            if summary_text:
                sources.append({
                    "cluster_id": cid,
                    "title": title,
                    "text": summary_text,
                })

        if sources:
            # Inject HDX quantitative data as Source 0 if available
            hdx_prefix = ""
            if hdx_context:
                try:
                    from hdx_enrichment import format_hdx_summary_for_prompt
                    hdx_prefix = format_hdx_summary_for_prompt(hdx_context)
                except Exception as exc:
                    logger.warning("HDX enrichment for executive summary failed: %s", exc)

            context_str = _format_numbered_context(sources)
            if hdx_prefix:
                context_str = hdx_prefix + context_str

            summary_prompt = _SITREP_SUMMARY_TEMPLATE.format(context=context_str)

            try:
                summary = llm_client.chat_simple(
                    user_prompt=summary_prompt,
                    max_tokens=LLM_MAX_TOKENS_SUMMARY,
                ).strip()
            except Exception as exc:
                logger.error("SITREP executive summary generation failed: %s", exc)
                summary = "The provided sources offer limited information for a comprehensive overview."

            cited_numbers = sorted({int(m) for m in re.findall(r"\[(\d+)\]", summary)})
            cited_paragraphs: dict[str, str] = {}
            cited_paragraphs_meta: dict[str, dict] = {}
            for num in cited_numbers:
                idx = num - 1
                if 0 <= idx < len(sources):
                    src = sources[idx]
                    cited_paragraphs[str(num)] = src["text"]

                    cid = src["cluster_id"]
                    meta_values = list(
                        cluster_summaries.get(cid, {}).get("used_contexts_meta", {}).values()
                    )
                    urls = [m.get("url", "") for m in meta_values if m.get("url", "")]
                    rep_url = max(set(urls), key=urls.count) if urls else ""

                    cited_paragraphs_meta[str(num)] = {"title": src["title"], "url": rep_url}

            logger.info(
                "SITREP executive summary completed: %d sources, %d citations, %d words.",
                len(sources), len(cited_numbers), len(summary.split()),
            )

            return {
                "summary": summary,
                "cited_paragraphs": cited_paragraphs,
                "cited_paragraphs_meta": cited_paragraphs_meta,
                "full_paragraphs": [s["text"] for s in sources],
            }

        logger.warning("cluster_summaries provided but no cluster has a summary, falling back.")
    # =========================================================================
    # PATH B: Fallback from raw chunks
    # =========================================================================

    # 1. Collect all new_used_contexts with metadata (dedup, text → meta)
    all_contexts_meta: dict[str, dict] = {}  # text → {title, url}
    for answer in postprocessed_answers:
        contexts = answer.get("new_used_contexts", [])
        metas = answer.get("new_used_contexts_meta", [])
        if not contexts:
            contexts = answer.get("retrieved_contexts", [])
            metas = answer.get("retrieved_contexts_meta", [])
        for ctx, meta in zip_longest(contexts, metas, fillvalue={}):
            if ctx and ctx.strip() and ctx not in all_contexts_meta:
                meta = meta or {}
                all_contexts_meta[ctx] = {
                    "title": meta.get("title", ""),
                    "url": meta.get("url", ""),
                }

    full_paragraphs = sorted(list(all_contexts_meta.keys()))
    logger.info("%d unique paragraphs collected for executive summary.", len(full_paragraphs))

    if not full_paragraphs:
        logger.warning("No paragraphs found for executive summary.")
        return {
            "summary": "The provided sources do not contain information relevant to describing a situation.",
            "cited_paragraphs": {},
            "cited_paragraphs_meta": {},
            "full_paragraphs": [],
        }

    # 2. Generate sub-queries + RRF
    subqueries = _generate_subqueries(_EXEC_SUMMARY_QUERY)

    ranked_lists = []
    for sq in subqueries:
        results = _simple_retrieve(sq, corpus=full_paragraphs, k=RETRIEVAL_TOP_K_SUMMARY)
        ranked_lists.append(results)

    fused = _reciprocal_rank_fusion(ranked_lists, k=RRF_K)
    top_chunks = fused[:RETRIEVAL_TOP_K_SUMMARY]

    # 3. Format context and send to LLM
    context_items = [{"title": "", "text": c["text"]} for c in top_chunks]
    context_str = _format_numbered_context(context_items)
    context_texts = [c["text"] for c in top_chunks]

    summary_prompt = _EXEC_SUMMARY_TEMPLATE.format(context=context_str)

    try:
        summary = llm_client.chat_simple(
            user_prompt=summary_prompt,
            max_tokens=LLM_MAX_TOKENS_SUMMARY,
        ).strip()
    except Exception as exc:
        logger.error("Executive summary generation failed: %s", exc)
        summary = "The provided sources offer limited information for a comprehensive overview."

    # 4. Resolve used citations
    cited_numbers = sorted({int(m) for m in re.findall(r"\[(\d+)\]", summary)})
    cited_paragraphs: dict[str, str] = {}
    cited_paragraphs_meta: dict[str, dict] = {}

    for num in cited_numbers:
        idx = num - 1
        if 0 <= idx < len(context_texts):
            text = context_texts[idx]
            cited_paragraphs[str(num)] = text
            cited_paragraphs_meta[str(num)] = all_contexts_meta.get(text, {"title": "", "url": ""})

    logger.info(
        "Executive summary completed: %d citations, %d words.",
        len(cited_numbers), len(summary.split()),
    )

    return {
        "summary": summary,
        "cited_paragraphs": cited_paragraphs,
        "cited_paragraphs_meta": cited_paragraphs_meta,
        "full_paragraphs": full_paragraphs,
    }
