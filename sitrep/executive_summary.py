"""
sitrep_pipeline/executive_summary.py
Tüm cevaplardan kullanılan context'leri toplayarak executive summary üretir.

Sürüm 2 değişiklikleri:
- cluster_summaries parametresi eklendi → SITREP formatı için cluster özetlerinden üretim
- Citation metadata (title/url) artık cited_paragraphs_meta ile taşınıyor
- report_assembly.py fuzzy match fallback'e gerek kalmadı
"""

import re
import logging
from itertools import zip_longest
from typing import List, Dict, Optional

from config import (
    RETRIEVAL_TOP_K_SUMMARY,
    RRF_K,
    RRF_NUM_SUBQUERIES,
    LLM_MAX_TOKENS_SUMMARY,
)
import llm_client
from rag_answers import _generate_subqueries, _reciprocal_rank_fusion

logger = logging.getLogger(__name__)

_EXEC_SUMMARY_QUERY = "Generate a summary of the current situation."


# ---------------------------------------------------------------------------
# Prompt: Cluster özetlerinden SITREP executive summary (tercih edilen yol)
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
# Prompt: Ham chunk'lardan executive summary (fallback yolu)
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


def _format_numbered_context(items: List[Dict]) -> str:
    """
    [{"title": str, "text": str}, ...] listesini numaralı kaynak formatına çevirir.
    title varsa başlık satırı eklenir.
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
    corpus: List[str],
    k: int,
) -> List[Dict]:
    """
    Corpus (string listesi) üzerinde embedding tabanlı retrieval yapar.
    Küçük pool'lar için ColBERT yerine basit cosine similarity kullanır.

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
    postprocessed_answers: List[Dict],
    cluster_summaries: Optional[Dict] = None,
) -> Dict:
    """
    Executive summary üretir.

    Tercih edilen yol (cluster_summaries verildiğinde):
        Her cluster başlığı + narrative özeti kaynak olarak kullanılır.
        SITREP formatında 2-4 paragraf üretir.

    Fallback yol (cluster_summaries None ise):
        Tüm cevapların kullanılan context'lerini RRF ile retrieval yapar.
        Ham chunk'lardan özet üretir.

    Args:
        postprocessed_answers: citation_postprocess.postprocess_citations() çıktısı
        cluster_summaries    : cluster_summary.generate_cluster_summaries() çıktısı (opsiyonel)

    Returns:
        {
          "summary"              : str,
          "cited_paragraphs"     : [str],
          "cited_paragraphs_meta": [{"title": str, "url": str}],  # cited_paragraphs ile paralel
          "full_paragraphs"      : [str],
        }
    """

    # =========================================================================
    # YOL A: Cluster özetlerinden SITREP formatında üretim
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
            context_str = _format_numbered_context(sources)
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
            cited_paragraphs: List[str] = []
            cited_paragraphs_meta: List[Dict] = []
            for num in cited_numbers:
                idx = num - 1
                if 0 <= idx < len(sources):
                    src = sources[idx]
                    cited_paragraphs.append(src["text"])

                    # Cluster'ın used_contexts_meta'sından en sık tekrar eden URL'yi seç
                    cid = src["cluster_id"]
                    meta_values = list(
                        cluster_summaries.get(cid, {}).get("used_contexts_meta", {}).values()
                    )
                    urls = [m.get("url", "") for m in meta_values if m.get("url", "")]
                    rep_url = max(set(urls), key=urls.count) if urls else ""

                    cited_paragraphs_meta.append({"title": src["title"], "url": rep_url})

            logger.info(
                "SITREP executive summary tamamlandı: %d kaynak, %d citation, %d kelime.",
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
    # YOL B: Ham chunk'lardan fallback
    # =========================================================================

    # 1. Tüm new_used_contexts'i metadata ile birlikte topla (dedup, text → meta)
    all_contexts_meta: Dict[str, Dict] = {}  # text → {title, url}
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
            "cited_paragraphs": [],
            "cited_paragraphs_meta": [],
            "full_paragraphs": [],
        }

    # 2. Sub-query üret + RRF
    subqueries = _generate_subqueries(_EXEC_SUMMARY_QUERY)

    ranked_lists = []
    for sq in subqueries:
        results = _simple_retrieve(sq, corpus=full_paragraphs, k=RETRIEVAL_TOP_K_SUMMARY)
        ranked_lists.append(results)

    fused = _reciprocal_rank_fusion(ranked_lists, k=RRF_K)
    top_chunks = fused[:RETRIEVAL_TOP_K_SUMMARY]

    # 3. Context formatla ve LLM'e gönder
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

    # 4. Kullanılan citation'ları çöz
    cited_numbers = sorted({int(m) for m in re.findall(r"\[(\d+)\]", summary)})
    cited_paragraphs = []
    cited_paragraphs_meta = []

    for num in cited_numbers:
        idx = num - 1
        if 0 <= idx < len(context_texts):
            text = context_texts[idx]
            cited_paragraphs.append(text)
            cited_paragraphs_meta.append(all_contexts_meta.get(text, {"title": "", "url": ""}))

    logger.info(
        "Executive summary tamamlandı: %d citation, %d kelime.",
        len(cited_numbers), len(summary.split()),
    )

    return {
        "summary": summary,
        "cited_paragraphs": cited_paragraphs,
        "cited_paragraphs_meta": cited_paragraphs_meta,
        "full_paragraphs": full_paragraphs,
    }
