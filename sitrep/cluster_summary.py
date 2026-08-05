"""
sitrep_pipeline/cluster_summary.py
Combines answers for each cluster into a single narrative summary.

Original Stage 4 (4-Summary for each cluster.ipynb) logic:
1. Add citation number offset for each answer (prevent overlap)
2. Combine all answers → narrative integration via LLM
3. Generate SITREP headline for each cluster
"""

import logging
import re

import llm_client

from config import LLM_MAX_TOKENS_HEADLINE, LLM_MAX_TOKENS_SUMMARY, LLM_MODEL_ANSWERS, LLM_TEMPERATURE_ANSWERS

logger = logging.getLogger(__name__)

# Original offset: +i*10 for each answer
CITATION_OFFSET_STEP: int = 10


# ---------------------------------------------------------------------------
# Apply citation offset
# ---------------------------------------------------------------------------


def _apply_citation_offset(answer_text: str, offset: int) -> str:
    """
    Replaces all [n] citations in the answer text with [n + offset].
    Replaces from largest to smallest number (prevent overlap).
    """
    citations_found = set(re.findall(r"\[(\d+)\]", answer_text))
    sorted_citations = sorted([int(c) for c in citations_found], reverse=True)

    modified = answer_text
    for old_num in sorted_citations:
        new_num = old_num + offset
        modified = re.sub(
            rf"\[{re.escape(str(old_num))}\]",
            f"[{new_num}]",
            modified,
        )
    return modified


def _offset_contexts(
    new_citations: list[int],
    new_used_contexts: list[str],
    offset: int,
) -> dict[int, str]:
    """
    {old_citation_num: context_text} → {old_citation_num + offset: context_text}
    """
    result: dict[int, str] = {}
    for old_num, ctx in zip(new_citations, new_used_contexts, strict=False):
        result[old_num + offset] = ctx
    return result


def _offset_contexts_meta(
    new_citations: list[int],
    new_used_contexts_meta: list[dict],
    offset: int,
) -> dict[int, dict]:
    """
    {old_citation_num: meta_dict} → {old_citation_num + offset: meta_dict}
    meta_dict = {title: str, url: str, ...}
    """
    result: dict[int, dict] = {}
    for old_num, meta in zip(new_citations, new_used_contexts_meta, strict=False):
        result[old_num + offset] = meta or {}
    return result


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_INTEGRATE_SYSTEM = (
    "You are a helpful assistant specialized in combining humanitarian report text "
    "into cohesive narratives while preserving all citations."
)

_INTEGRATE_USER_TEMPLATE = """\
Your task is to integrate the following pieces of text into a single, cohesive, and flowing narrative. The goal is to present as much of the original information as possible, not to summarize it briefly.

The text contains information with citations, formatted as `[number]`. It is crucial that you adhere to the following rules:

1.  **Integrate all key information**: Combine sentences and ideas from the input to form a comprehensive and coherent text. Aim to include a good portion, if not all, of the provided details.
2.  **Maintain original citations**: Every piece of information you include in the integrated text must retain its original citation(s).
3.  **Handle citations when combining**: If you rephrase or combine sentences containing information from multiple sources, ensure that *all* relevant original citation numbers for that combined information are included at the end of the new sentence. For example, if a new sentence merges details from original sentences cited `[1]` and `[5]`, the new sentence should be followed by `[1][5]`.
4.  **Ensure logical flow**: Arrange the information in a way that creates a natural and readable progression of ideas, even if it means reordering content from the original input.
5.  **Avoid external knowledge**: Your output must be based *solely* on the information provided in the input text. Do not introduce any outside facts or personal opinions.

Here is the text to integrate:
{text_to_integrate}
"""

_TITLE_USER_TEMPLATE = """\
You are creating a title for a situational report.

Read the following summary and generate a title that:
- Clearly identifies the situation, topic, or issue being reported
- Is appropriate for a professional situational report (SITREP style)
- Is direct and informative (8-12 words)
- Uses clear, actionable language suitable for decision-makers
- Does not include meta-phrases like "Report on" or "Summary of"

Summary:
{summary_text}

Return only the title, nothing else.
"""


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


def generate_cluster_summaries(
    postprocessed_answers: list[dict],
    clusters: dict,
) -> dict:
    """
    Combines answers for each cluster and generates a narrative summary and headline.

    Args:
        postprocessed_answers: Output of citation_postprocess.postprocess_citations()
        clusters              : Output of clustering.run_clustering()

    Returns:
        {
          cluster_id: {
            "summary"      : str,   # narrative text with citations
            "used_contexts": {citation_num: text, ...},
            "title"        : str,   # SITREP headline
          }
        }
    """
    # Group answers by cluster_id
    cluster_groups: dict[str, list[dict]] = {}
    for answer in postprocessed_answers:
        cid = str(answer["cluster_id"])
        cluster_groups.setdefault(cid, []).append(answer)

    final_output: dict = {}

    for cluster_id, answers in cluster_groups.items():
        logger.info("Generating summary for cluster %s (%d answers)", cluster_id, len(answers))

        # 1. Apply citation offset
        modified_texts: list[str] = []
        merged_contexts: dict[int, str] = {}
        merged_meta: dict[int, dict] = {}  # citation_num → {title, url}

        for i, answer in enumerate(answers):
            offset = i * CITATION_OFFSET_STEP
            original_answer = answer.get("updated_retrieved_answer", answer.get("retrieved_answer", ""))

            # Include only answers with citations
            if "[" not in original_answer:
                continue

            modified_text = _apply_citation_offset(original_answer, offset)
            modified_texts.append(modified_text)

            # Update context and metadata mapping
            ctx_map = _offset_contexts(
                answer.get("new_citations", []),
                answer.get("new_used_contexts", []),
                offset,
            )
            merged_contexts.update(ctx_map)

            meta_map = _offset_contexts_meta(
                answer.get("new_citations", []),
                answer.get("new_used_contexts_meta", []),
                offset,
            )
            merged_meta.update(meta_map)

        if not modified_texts:
            logger.warning("Cluster %s: no answers with citations, skipping summary.", cluster_id)
            headline = clusters.get(cluster_id, {}).get("cluster_headline", f"Cluster {cluster_id}")
            final_output[cluster_id] = {
                "summary": "",
                "used_contexts": {},
                "used_contexts_meta": {},
                "title": headline,
            }
            continue

        # 2. Combine all texts
        combined_text = "\n\n".join(modified_texts)
        integrate_prompt = _INTEGRATE_USER_TEMPLATE.format(text_to_integrate=combined_text)

        # 3. Narrative integration
        try:
            summary = llm_client.chat_simple(
                user_prompt=integrate_prompt,
                system_prompt=_INTEGRATE_SYSTEM,
                max_tokens=LLM_MAX_TOKENS_SUMMARY,
                model=LLM_MODEL_ANSWERS,
                temperature=LLM_TEMPERATURE_ANSWERS,
            )
        except Exception as exc:
            logger.error("Cluster %s narrative integration failed: %s", cluster_id, exc)
            summary = combined_text  # Use raw text

        # 4. Generate headline
        title_prompt = _TITLE_USER_TEMPLATE.format(summary_text=summary[:1500])
        try:
            title = llm_client.chat_simple(
                user_prompt=title_prompt,
                max_tokens=LLM_MAX_TOKENS_HEADLINE,
                model=LLM_MODEL_ANSWERS,
                temperature=LLM_TEMPERATURE_ANSWERS,
            )
            title = title.strip().strip('"').strip("'")
        except Exception as exc:
            logger.warning("Cluster %s title generation failed: %s", cluster_id, exc)
            title = clusters.get(cluster_id, {}).get("cluster_headline", f"Cluster {cluster_id}")

        final_output[cluster_id] = {
            "summary": summary.strip(),
            "used_contexts": merged_contexts,
            "used_contexts_meta": merged_meta,
            "title": title,
        }

        logger.info("  Cluster %s completed: title='%s'", cluster_id, title)

    return final_output
