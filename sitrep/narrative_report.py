"""
sitrep_pipeline/narrative_report.py
Generates a full narrative report from executive summary and cluster summaries.

Stage 8.5: One of the final stages of the pipeline — called before report assembly.

Output:
{
    "narrative_html": str,        # Full narrative report in HTML format
    "narrative_sources": {        # Used source references
        "cluster_titles": [str],
        "exec_summary_used": bool
    }
}
"""

import re
import logging
from typing import Dict, List, Optional

from config import (
    LLM_MAX_TOKENS_SUMMARY,
    LLM_MODEL_ANSWERS,
    LLM_TEMPERATURE_ANSWERS,
)
import llm_client

logger = logging.getLogger(__name__)

_NARRATIVE_SYSTEM = (
    "You are an expert humanitarian analyst writing Situation Reports (SITREPs). "
    "Your writing is clear, factual, and well-structured. You cite all claims with [N] notation."
)

_NARRATIVE_USER_TEMPLATE = """\
You are writing a comprehensive narrative Situation Report (SITREP) for the humanitarian crisis in **{country}** ({event}).

You have two main inputs:
1. An **Executive Summary** that provides an overall assessment
2. **Cluster Summaries** that provide detailed thematic analysis

Your task is to produce a **coherent, flowing narrative report** in HTML format.

**Structure the report with these HTML sections:**

<h2>1. Executive Overview</h2>
<p>A concise overview of the overall humanitarian situation (2-3 paragraphs). Use information from the Executive Summary.</p>

<h2>2. Detailed Situation Analysis</h2>
<p>For each major thematic area, write 1-2 paragraphs drawing from the cluster summaries. Organize by theme, not by cluster number. Merge related clusters into coherent thematic sections with appropriate subheadings.</p>

<h2>3. Key Findings & Trends</h2>
<p>Highlight the most critical findings, emerging trends, and data points from across all sources.</p>

<h2>4. Gaps & Recommendations</h2>
<p>Identify information gaps and provide actionable recommendations based on the evidence.</p>

**Rules:**
- Write in **prose**, not bullet points
- Every factual claim must cite its source using [N] notation where N is the source number
- When multiple sources support the same claim, combine citations like [1][3]
- Do NOT introduce information not present in the sources
- Use `<h3>` for sub-sections within the main sections if needed
- Do NOT include a `<html>`, `<head>`, or `<body>` tag — just the content sections
- Citation numbers must correspond accurately to the sources provided

---

**Source 0: Executive Summary**
{exec_summary}

{cluster_sources}

---

**Write the complete narrative report now:**"""


def _format_cluster_sources(cluster_summaries: Dict) -> tuple:
    """
    Converts cluster summaries to numbered source format.
    Returns: (source_text: str, source_meta: dict)
        source_meta maps source number → {title, url}
    """
    parts = []
    source_meta = {}
    num = 1
    for cid, cdata in sorted(cluster_summaries.items()):
        title = cdata.get("title", f"Cluster {cid}")
        summary = cdata.get("summary", "").strip()
        if summary:
            parts.append(f"**Source {num}: [{title}]**\n{summary}")
            # Collect representative URL from cluster's used_contexts_meta
            meta_values = list(cdata.get("used_contexts_meta", {}).values())
            urls = [m.get("url", "") for m in meta_values if isinstance(m, dict) and m.get("url")]
            rep_url = max(set(urls), key=urls.count) if urls else ""
            source_meta[str(num)] = {"title": title, "url": rep_url}
            num += 1
    return "\n\n".join(parts), source_meta


def generate_narrative_report(
    country: str,
    event: str,
    cluster_summaries: Dict,
    exec_summary: Dict,
) -> Dict:
    """
    Generates a full narrative report from executive summary and cluster summaries.

    Args:
        country          : Country name (used in prompt)
        event            : Event/crisis name
        cluster_summaries: Output of cluster_summary.generate_cluster_summaries()
        exec_summary     : Output of executive_summary.generate_executive_summary()

    Returns:
        {
            "narrative_html": str,
            "narrative_sources": {
                "cluster_titles": [str],
                "exec_summary_used": bool
            }
        }
    """
    summary_text = exec_summary.get("summary", "").strip()
    cluster_source_text, cluster_source_meta = _format_cluster_sources(cluster_summaries)

    event_label = event if event else country

    if not summary_text and not cluster_source_text:
        logger.warning("No content available for narrative report generation.")
        return {
            "narrative_html": (
                f"<h2>1. Executive Overview</h2>"
                f"<p>Insufficient data available to generate a narrative report for {country}.</p>"
            ),
            "narrative_sources": {
                "cluster_titles": [],
                "exec_summary_used": False,
            },
        }

    # Build source metadata for citations:
    # Source 0 = Executive Summary, Sources 1+ = Cluster Summaries
    # The narrative prompt labels them as "Source 0", "Source 1", etc.
    # We map these to {title, url} for clickable citations.
    exec_meta = exec_summary.get("cited_paragraphs_meta", {})
    # Find the most representative URL from exec summary citations
    exec_urls = [v.get("url", "") for v in exec_meta.values() if isinstance(v, dict) and v.get("url")]
    exec_rep_url = max(set(exec_urls), key=exec_urls.count) if exec_urls else ""
    exec_title = exec_summary.get("summary", "")[:80].strip() + "..." if len(exec_summary.get("summary", "")) > 80 else exec_summary.get("summary", "")

    # Combined source map: "0" = exec summary, "1".."N" = cluster summaries
    narrative_citation_meta = {"0": {"title": "Executive Summary", "url": exec_rep_url}}
    narrative_citation_meta.update(cluster_source_meta)

    prompt = _NARRATIVE_USER_TEMPLATE.format(
        country=country,
        event=event_label,
        exec_summary=summary_text or "(No executive summary available)",
        cluster_sources=cluster_source_text or "(No cluster summaries available)",
    )

    try:
        narrative_html = llm_client.chat_simple(
            user_prompt=prompt,
            system_prompt=_NARRATIVE_SYSTEM,
            max_tokens=LLM_MAX_TOKENS_SUMMARY * 2,
            model=LLM_MODEL_ANSWERS,
            temperature=LLM_TEMPERATURE_ANSWERS,
        ).strip()
    except Exception as exc:
        logger.error("Narrative report generation failed: %s", exc)
        narrative_html = _build_fallback_html(
            country, event_label, summary_text, cluster_summaries
        )

    seen = set()
    cluster_titles = []
    for cid, cdata in sorted(cluster_summaries.items()):
        title = cdata.get("title", f"Cluster {cid}")
        if title not in seen:
            cluster_titles.append(title)
            seen.add(title)

    logger.info(
        "Narrative report completed: %d clusters, %d words.",
        len(cluster_summaries),
        len(narrative_html.split()),
    )

    return {
        "narrative_html": narrative_html,
        "narrative_sources": {
            "cluster_titles": cluster_titles,
            "exec_summary_used": bool(summary_text),
            **narrative_citation_meta,
        },
    }


def _build_fallback_html(
    country: str,
    event: str,
    exec_summary_text: str,
    cluster_summaries: Dict,
) -> str:
    """
    Generates plain HTML fallback if LLM call fails.
    """
    html = f"<h2>1. Executive Overview</h2>\n"
    if exec_summary_text:
        html += f"<p>{exec_summary_text}</p>\n"
    else:
        html += f"<p>Overview for {country} — {event}.</p>\n"

    html += "\n<h2>2. Detailed Situation Analysis</h2>\n"
    for cid, cdata in sorted(cluster_summaries.items()):
        title = cdata.get("title", f"Cluster {cid}")
        summary = cdata.get("summary", "").strip()
        if summary:
            html += f"<h3>{title}</h3>\n<p>{summary}</p>\n"

    html += "\n<h2>3. Key Findings & Trends</h2>\n"
    html += "<p>Key findings are based on the cluster analyses above.</p>\n"

    html += "\n<h2>4. Gaps & Recommendations</h2>\n"
    html += "<p>Further analysis is needed to identify specific gaps and recommendations.</p>\n"

    return html