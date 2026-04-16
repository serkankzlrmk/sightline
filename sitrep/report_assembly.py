"""
sitrep_pipeline/report_assembly.py
Tüm pipeline çıktılarını final JSON ve Markdown raporuna dönüştürür.

Orijinal Stage 6 (6-Report Generation.ipynb) mantığı:
- LLM çağrısı yok — saf veri birleştirme
- Citation enrichment: her [n] citation'ı için {context, title, url} ekler
- QA filtresi: citation içermeyen veya "no clear answer" içerenleri çıkar
- viewer_v2.html ile uyumlu JSON şeması üretir
"""

import re
import json
import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import OUTPUT_REPORTS_DIR

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD: float = 0.7
MIN_SUBSTRING_LENGTH: int = 50


# ---------------------------------------------------------------------------
# Citation enrichment
# ---------------------------------------------------------------------------

def _build_metadata_lookup(
    postprocessed_answers: List[Dict],
) -> List[Dict]:
    """
    retrieved_contexts_meta verilerinden metadata arama tablosu oluşturur.
    Her girdi: {text: str, title: str, url: str}
    """
    seen: set = set()
    metadata: List[Dict] = []
    for answer in postprocessed_answers:
        for meta in answer.get("retrieved_contexts_meta", []):
            text = answer.get("retrieved_contexts", [])
            # meta ve text eşleşmesini retrieved_contexts sırasına göre yap
            pass
        # Daha temiz yaklaşım: tüm meta'ları contexts ile birlikte sakla
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
    metadata_list: List[Dict],
) -> Tuple[str, str]:
    """
    Bir context metni için en iyi eşleşen title ve url'yi döndür.
    Önce tam eşleşme, sonra substring, sonra fuzzy SequenceMatcher.

    Returns:
        (title, url)
    """
    if not context_text or not metadata_list:
        return ("", "")

    # 1. Tam eşleşme
    for item in metadata_list:
        if item.get("paragraph", "") == context_text:
            return (item.get("title", ""), item.get("url", ""))

    # 2. Substring eşleşme (yeterince uzunsa)
    if len(context_text) >= MIN_SUBSTRING_LENGTH:
        for item in metadata_list:
            para = item.get("paragraph", "")
            if context_text in para or para in context_text:
                return (item.get("title", ""), item.get("url", ""))

    # 3. Fuzzy eşleşme
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
    citation_map: Dict,
    metadata_list: List[Dict],
) -> Dict:
    """
    {citation_num: context_text} → {citation_num: {context, title, url}}
    """
    enriched: Dict = {}
    for num, text in citation_map.items():
        title, url = _find_metadata_for_context(text, metadata_list)
        enriched[str(num)] = {
            "context": text,
            "title": title,
            "url": url,
        }
    return enriched


# ---------------------------------------------------------------------------
# QA filtresi
# ---------------------------------------------------------------------------

def _is_valid_answer(answer_text: str) -> bool:
    """
    Citation içermeyen veya 'no clear answer' içeren cevapları eleme.
    """
    if not answer_text:
        return False
    has_citation = "[" in answer_text and "]" in answer_text
    has_no_clear = bool(re.search(r"no clear answer", answer_text, re.IGNORECASE))
    return has_citation and not has_no_clear


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def assemble_report(
    country: str,
    event: str,
    clusters: Dict,
    filtered_questions: Dict,
    postprocessed_answers: List[Dict],
    cluster_summaries: Dict,
    exec_summary: Dict,
    narrative: Optional[Dict] = None,
    themes: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict:
    """
    Tüm pipeline çıktılarından final rapor JSON'ını üretir.

    Returns:
        Viewer ile uyumlu JSON yapısı:
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

    # Metadata lookup tablosu oluştur
    metadata_list = _build_metadata_lookup(postprocessed_answers)

    # ---- Executive summary ----
    summary_text = exec_summary.get("summary", "")
    cited_paragraphs = exec_summary.get("cited_paragraphs", [])
    cited_paragraphs_meta = exec_summary.get("cited_paragraphs_meta", [])

    # Summary contexts: citation num → {context, title, url}
    summary_citation_nums = [int(m) for m in re.findall(r"\[(\d+)\]", summary_text)]
    summary_contexts: Dict = {}
    for num in set(summary_citation_nums):
        idx = num - 1
        if 0 <= idx < len(cited_paragraphs):
            text = cited_paragraphs[idx]
            # Önce cited_paragraphs_meta'dan doğrudan metadata'yı kullan (daha güvenilir)
            if idx < len(cited_paragraphs_meta):
                meta = cited_paragraphs_meta[idx]
                title = meta.get("title", "")
                url = meta.get("url", "")
                # URL yoksa fuzzy match ile doldur (ham chunk yolunda gerekebilir)
                if not url:
                    _, url_fb = _find_metadata_for_context(text, metadata_list)
                    url = url_fb
            else:
                # Fallback: fuzzy match (geriye dönük uyum)
                title, url = _find_metadata_for_context(text, metadata_list)
            summary_contexts[str(num)] = {"context": text, "title": title, "url": url}

    # ---- QA veriyi cluster'a göre grupla ----
    qa_by_cluster: Dict[str, List[Dict]] = {}
    for answer in postprocessed_answers:
        cid = str(answer["cluster_id"])
        answer_text = answer.get("updated_retrieved_answer", answer.get("retrieved_answer", ""))

        if not _is_valid_answer(answer_text):
            continue

        # Context map: {citation_num (int): text}
        new_citations: List[int] = answer.get("new_citations", [])
        new_contexts: List[str] = answer.get("new_used_contexts", [])
        new_metas: List[Dict] = answer.get("new_used_contexts_meta", [])
        retrieved_contexts: List[str] = answer.get("retrieved_contexts", [])
        retrieved_metas: List[Dict] = answer.get("retrieved_contexts_meta", [])

        context_map: Dict[int, str] = {
            num: text
            for num, text in zip(new_citations, new_contexts)
            if text
        }
        # Metadata map doğrudan post-process'ten al (fuzzy match gereksiz)
        meta_map: Dict[int, Dict] = {
            num: m
            for num, m in zip(new_citations, new_metas)
        }

        # Cevap içindeki tüm [n] referanslarını da ekle (context_map'te yoksa)
        for m in re.findall(r"\[(\d+)\]", answer_text):
            num = int(m)
            if num not in context_map and 0 < num <= len(retrieved_contexts):
                context_map[num] = retrieved_contexts[num - 1]
            if num not in meta_map and 0 < num <= len(retrieved_metas):
                meta_map[num] = retrieved_metas[num - 1]

        # used_contexts: citation_num → {context, title, url}
        enriched: Dict = {}
        for num, text in context_map.items():
            m = meta_map.get(num, {})
            title = m.get("title", "")
            url = m.get("url", "")
            # Fallback: fuzzy match (meta yoksa)
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
    output_clusters: List[Dict] = []
    for cluster_id, cluster_data in clusters.items():
        qa_items = qa_by_cluster.get(cluster_id, [])
        if not qa_items:
            continue  # QA'sız cluster'ları dahil etme

        # Başlık: cluster_summaries'den geliyorsa onu kullan
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

    # Narrative report (opsiyonel — yeni stage)
    if narrative:
        report["narrative_html"] = narrative.get("narrative_html", "")
        report["narrative_sources"] = narrative.get("narrative_sources", {})

    logger.info(
        "Rapor hazır: %d cluster, %d toplam QA",
        len(output_clusters),
        sum(len(c["questions_and_answers"]) for c in output_clusters),
    )
    return report


def save_report(
    report: Dict,
    country: str,
    event: str,
    output_dir: Optional[Path] = None,
    suffix: str = "",
) -> Path:
    """
    Raporu JSON formatında diske kaydeder.

    Returns:
        Kaydedilen dosyanın yolu.
    """
    out_dir = output_dir or OUTPUT_REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{country}_{event}{suffix}"
    out_path = out_dir / f"{file_name}_report.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info("Rapor kaydedildi: %s", out_path)
    return out_path


def generate_markdown(report: Dict) -> str:
    """
    Rapor dict'inden Markdown metin üretir.
    """
    file_name = report.get("file_name", "Report")
    md = f"# {file_name}\n\n"
    md += "## Summary\n\n"
    md += f"{report.get('summary', '')}\n\n"
    md += "## Questions and Answers\n\n"

    for cluster in report.get("clusters", []):
        if cluster.get("questions_and_answers"):
            md += f"### {cluster['cluster_headline']}\n\n"
            for qa in cluster["questions_and_answers"]:
                md += f"**Question:** {qa['question']}\n\n"
                md += f"**Answer:** {qa['updated_retrieved_answer']}\n\n"

    return md
