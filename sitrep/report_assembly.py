"""
sitrep_pipeline/report_assembly.py
Converts all pipeline outputs into a final JSON and Markdown report.

Original Stage 6 (6-Report Generation.ipynb) logic:
- No LLM calls — pure data assembly
- Citation enrichment: adds {context, title, url} for each [n] citation
- QA filter: removes entries without citations or containing "no clear answer"
- Produces a JSON schema compatible with viewer_v2.html
"""

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

from config import OUTPUT_REPORTS_DIR

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD: float = 0.7
MIN_SUBSTRING_LENGTH: int = 50


# ---------------------------------------------------------------------------
# Citation enrichment
# ---------------------------------------------------------------------------

def _build_metadata_lookup(
    postprocessed_answers: list[dict],
) -> list[dict]:
    """
    Builds a metadata lookup table from retrieved_contexts_meta data.
    Each entry: {text: str, title: str, url: str}
    """
    seen: set = set()
    metadata: list[dict] = []
    for answer in postprocessed_answers:
        for meta in answer.get("retrieved_contexts_meta", []):
            text = answer.get("retrieved_contexts", [])
            # Match meta and text by retrieved_contexts order
            pass
        # Cleaner approach: store all metas together with contexts
        contexts = answer.get("retrieved_contexts", [])
        metas = answer.get("retrieved_contexts_meta", [])
        for ctx, meta in zip(contexts, metas):
            key = ctx[:100]
            if key not in seen:
                seen.add(key)
                metadata.append({
                    "paragraph": ctx,
                    "title": meta.get("title", ""),
                    "url": meta.get("url", ""),
                })
    return metadata


def _find_metadata_for_context(
    context_text: str,
    metadata_list: list[dict],
) -> tuple[str, str]:
    """
    Returns the best matching title and URL for a context text.
    First exact match, then substring, then fuzzy SequenceMatcher.

    Returns:
        (title, url)
    """
    if not context_text or not metadata_list:
        return ("", "")

    # 1. Exact match
    for item in metadata_list:
        if item.get("paragraph", "") == context_text:
            return (item.get("title", ""), item.get("url", ""))

    # 2. Substring match (if long enough)
    if len(context_text) >= MIN_SUBSTRING_LENGTH:
        for item in metadata_list:
            para = item.get("paragraph", "")
            if context_text in para or para in context_text:
                return (item.get("title", ""), item.get("url", ""))

    # 3. Fuzzy match
    best_ratio = 0.0
    best_item = None
    for item in metadata_list:
        para = item.get("paragraph", "")
        ratio = SequenceMatcher(None, context_text[:400], para[:400]).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_item = item

    if best_item and best_ratio >= SIMILARITY_THRESHOLD:
        return (best_item.get("title", ""), best_item.get("url", ""))

    return ("", "")


def _enrich_contexts(
    citation_map: dict,
    metadata_list: list[dict],
) -> dict:
    """
    {citation_num: context_text} → {citation_num: {context, title, url}}
    """
    enriched: dict = {}
    for num, text in citation_map.items():
        title, url = _find_metadata_for_context(text, metadata_list)
        enriched[str(num)] = {
            "context": text,
            "title": title,
            "url": url,
        }
    return enriched


# ---------------------------------------------------------------------------
# QA filter
# ---------------------------------------------------------------------------

def _is_valid_answer(answer_text: str) -> bool:
    """
    Filters out answers without citations or containing 'no clear answer'.
    """
    if not answer_text:
        return False
    has_citation = "[" in answer_text and "]" in answer_text
    has_no_clear = bool(re.search(r"no clear answer", answer_text, re.IGNORECASE))
    return has_citation and not has_no_clear


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def assemble_report(
    country: str,
    event: str,
    clusters: dict,
    filtered_questions: dict,
    postprocessed_answers: list[dict],
    cluster_summaries: dict,
    exec_summary: dict,
    narrative: dict | None = None,
    themes: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    hdx_context: dict | None = None,
) -> dict:
    """
    Produces the final report JSON from all pipeline outputs.

    Returns:
        Viewer-compatible JSON structure:
        {
          file_name: str,
          summary: str,
          summary_contexts: {n: {context, title, url}},
          clusters: [
            {
              cluster_id: str,
              cluster_headline: str,
              questions_and_answers: [
                {
                  question: str,
                  updated_retrieved_answer: str,
                  used_contexts: {n: {context, title, url}}
                }
              ]
            }
          ]
        }
    """
    file_name = f"{country}_{event}"
    logger.info("Assembling report: %s", file_name)

    # Build metadata lookup table
    metadata_list = _build_metadata_lookup(postprocessed_answers)

    # ---- Executive summary ----
    summary_text = exec_summary.get("summary", "")
    cited_paragraphs = exec_summary.get("cited_paragraphs", {})
    cited_paragraphs_meta = exec_summary.get("cited_paragraphs_meta", {})

    # Summary contexts: citation num → {context, title, url}
    summary_citation_nums = [int(m) for m in re.findall(r"\[(\d+)\]", summary_text)]
    summary_contexts: dict = {}
    for num in set(summary_citation_nums):
        key = str(num)
        text = cited_paragraphs.get(key, "")
        if text:
            meta = cited_paragraphs_meta.get(key, {})
            title = meta.get("title", "")
            url = meta.get("url", "")
            if not url:
                _, url_fb = _find_metadata_for_context(text, metadata_list)
                url = url_fb
            summary_contexts[key] = {"context": text, "title": title, "url": url}

    # ---- Group QA data by cluster ----
    qa_by_cluster: dict[str, list[dict]] = {}
    for answer in postprocessed_answers:
        cid = str(answer["cluster_id"])
        answer_text = answer.get("updated_retrieved_answer", answer.get("retrieved_answer", ""))

        if not _is_valid_answer(answer_text):
            continue

        # Context map: {citation_num (int): text}
        new_citations: list[int] = answer.get("new_citations", [])
        new_contexts: list[str] = answer.get("new_used_contexts", [])
        new_metas: list[dict] = answer.get("new_used_contexts_meta", [])
        retrieved_contexts: list[str] = answer.get("retrieved_contexts", [])
        retrieved_metas: list[dict] = answer.get("retrieved_contexts_meta", [])

        context_map: dict[int, str] = {
            num: text
            for num, text in zip(new_citations, new_contexts)
            if text
        }
        # Metadata map directly from post-process (fuzzy match not needed)
        meta_map: dict[int, dict] = {
            num: m
            for num, m in zip(new_citations, new_metas)
        }

        # Also add all [n] references in the answer text (if not in context_map)
        for m in re.findall(r"\[(\d+)\]", answer_text):
            num = int(m)
            if num not in context_map and 0 < num <= len(retrieved_contexts):
                context_map[num] = retrieved_contexts[num - 1]
            if num not in meta_map and 0 < num <= len(retrieved_metas):
                meta_map[num] = retrieved_metas[num - 1]

        # used_contexts: citation_num → {context, title, url}
        enriched: dict = {}
        for num, text in context_map.items():
            m = meta_map.get(num, {})
            title = m.get("title", "")
            url = m.get("url", "")
            # Fallback: fuzzy match (if no meta)
            if not url:
                title_fb, url_fb = _find_metadata_for_context(text, metadata_list)
                title = title or title_fb
                url = url or url_fb
            enriched[str(num)] = {"context": text, "title": title, "url": url}

        qa_by_cluster.setdefault(cid, []).append({
            "question": answer["question"],
            "updated_retrieved_answer": answer_text,
            "used_contexts": enriched,
        })

    # ---- Cluster listesi ----
    output_clusters: list[dict] = []
    for cluster_id, cluster_data in clusters.items():
        qa_items = qa_by_cluster.get(cluster_id, [])
        if not qa_items:
            continue  # Skip clusters without QA

        # Title: use from cluster_summaries if available
        cluster_title = (
            cluster_summaries.get(cluster_id, {}).get("title")
            or cluster_data.get("cluster_headline", f"Cluster {cluster_id}")
        )

        output_clusters.append({
            "cluster_id": cluster_id,
            "cluster_headline": cluster_title,
            "questions_and_answers": qa_items,
        })

    report = {
        "file_name": file_name,
        "summary": summary_text,
        "summary_contexts": summary_contexts,
        "clusters": output_clusters,
    }

    # Filtre bilgisi
    if themes:
        report["themes"] = themes
    if date_from:
        report["date_from"] = date_from
    if date_to:
        report["date_to"] = date_to

    # Narrative report (optional — new stage)
    if narrative:
        report["narrative_html"] = narrative.get("narrative_html", "")
        report["narrative_sources"] = narrative.get("narrative_sources", {})

    # HDX quantitative data (optional — enrichment)
    if hdx_context:
        report["hdx_data"] = {
            "country": hdx_context.get("country", country),
            "country_code": hdx_context.get("country_code", ""),
            "summary": hdx_context.get("summary", {}),
        }

    logger.info(
        "Report ready: %d clusters, %d total QA",
        len(output_clusters),
        sum(len(c["questions_and_answers"]) for c in output_clusters),
    )
    return report


def save_report(
    report: dict,
    country: str,
    event: str,
    output_dir: Path | None = None,
    suffix: str = "",
) -> Path:
    """
    Saves the report to disk in JSON format.

    Returns:
        Path to the saved file.
    """
    out_dir = output_dir or OUTPUT_REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{country}_{event}{suffix}"
    out_path = out_dir / f"{file_name}_report.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info("Report saved: %s", out_path)
    return out_path


def generate_markdown(report: dict) -> str:
    """
    Generates Markdown text from a report dict.
    """
    file_name = report.get("file_name", "Report")
    md = f"# {file_name}\n\n"
    md += "## Summary\n\n"
    md += f"{report.get('summary', '')}\n\n"

    # HDX quantitative data section
    hdx_data = report.get("hdx_data", {})
    if hdx_data and hdx_data.get("summary"):
        md += "## Key Humanitarian Data (HDX)\n\n"
        hdx_summary = hdx_data["summary"]
        if "refugees_total" in hdx_summary and hdx_summary["refugees_total"]:
            md += f"- **Total Refugees**: {hdx_summary['refugees_total']:,.0f}\n"
        if "idps_total" in hdx_summary and hdx_summary["idps_total"]:
            md += f"- **Total IDPs**: {hdx_summary['idps_total']:,.0f}\n"
        required = hdx_summary.get("funding_required_usd", 0) or 0
        funded = hdx_summary.get("funding_funded_usd", 0) or 0
        if required > 0:
            pct = (funded / required * 100) if required > 0 else 0
            md += f"- **Funding**: ${funded:,.0f} of ${required:,.0f} ({pct:.1f}%)\n"
        if "risk_class" in hdx_summary:
            md += f"- **INFORM Risk**: {hdx_summary['risk_class']} (Global Rank #{hdx_summary.get('global_rank', '?')})\n"
        md += "\n*Source: Humanitarian Data Exchange (HDX)*\n\n"

    md += "## Questions and Answers\n\n"

    for cluster in report.get("clusters", []):
        if cluster.get("questions_and_answers"):
            md += f"### {cluster['cluster_headline']}\n\n"
            for qa in cluster["questions_and_answers"]:
                md += f"**Question:** {qa['question']}\n\n"
                md += f"**Answer:** {qa['updated_retrieved_answer']}\n\n"

    return md
