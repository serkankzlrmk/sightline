"""
sitrep_pipeline/question_generation.py
Cluster başına soru üretimi ve deduplication.

Orijinal Stage 2.0 (2.0-Questions-generation.ipynb) mantığı:
- Her cluster için 3 kez LLM çağrısı (Prompt 1 şablonu)
- T5-canard KALDIRILDI (soru genişletme)
- Dedup: cosine similarity (DefaultEmbeddingFunction) — CrossEncoder yerine
"""

import re
import random
import logging
from typing import List, Dict, Tuple

import numpy as np

from config import (
    QUESTION_RUNS_PER_CLUSTER,
    QUESTION_DEDUP_THRESHOLD,
    MAX_QUESTIONS_PER_CLUSTER,
    LLM_MAX_TOKENS_DEFAULT,
    LLM_MODEL_QUESTIONS,
    LLM_TEMPERATURE_QUESTIONS,
)
import llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt 1 şablonu (orijinalden birebir alındı)
# ---------------------------------------------------------------------------

# Prompt'a dahil edilecek max makale sayısı ve karakter limiti
_MAX_ARTICLES_IN_PROMPT: int = 20
_MAX_ARTICLE_CHARS: int = 500


def _build_prompt(headline: str, articles: List[str], event: str, country: str) -> str:
    """Orijinal Prompt 1 şablonunu oluşturur.
    
    Token limitini aşmamak için rastgele örnekleme ve kırpma uygulanır.
    """
    # Token limitini aşmamak için rastgele örnekle ve kırp
    sampled = random.sample(articles, min(_MAX_ARTICLES_IN_PROMPT, len(articles)))

    prompt = f"""You are an expert in developing strategic and tactical questions to analyze and address humanitarian situations, based exclusively on the provided data.
Your task is to generate clear, specific, and insightful questions tailored for a humanitarian situational report.

Input:
You will be provided with:
1.  A set of paragraphs extracted from humanitarian documents.
2.  A headline summarizing the cluster.
3.  The specific event: {event}.
4.  The relevant country: {country}.

Instructions for Generating Questions:

1.  Data-Driven: Each question must rely *solely* on the information present in the provided text. Do not introduce external knowledge or ask about information not contained in the text.
2.  Relevance: Ensure every question is directly relevant to the content of the provided paragraphs, the specified {event}, and the {country}. The questions should aim to capture key aspects of the humanitarian situation described.
3.  Precision: Questions must be well-defined, focused, and unambiguous.
4.  Action-Oriented: Frame questions to elicit actionable insights that can support humanitarian decision-making and response, based *only* on the data provided.
5.  Explicit Acronyms: If an acronym is used in a question (e.g., WHO), it must be explicitly defined within that question (e.g., "What actions has the World Health Organization (WHO) taken..."), assuming the definition is available or inferable from the provided text. If the text uses an acronym without defining it, the question may also use it if it's central to the text, but define it if possible from context.
6.  Neutral and Non-Political: Questions must maintain a strictly neutral tone. Avoid any political content, expressions of personal or subjective opinions, or leading questions.

Output Format Requirements:

* Questions Only: Your output must consist *only* of the generated questions. Do not include any introductory text, preambles, explanations, or concluding remarks.
* No Categorization or Prefixes: Do not add any category titles, labels, or any other descriptive text before individual questions.
* No Formatting: Generate questions in plain text. Do not use any formatting such as bolding, italics, or asterisks.
* Listing: Present the questions as a simple numbered list. Each question on a new line.

Headline: {headline}

Content:
"""
    for idx, article in enumerate(sampled):
        text = " ".join(article.split("\n")).strip()
        # Çok uzun metinleri kırp
        if len(text) > _MAX_ARTICLE_CHARS:
            text = text[:_MAX_ARTICLE_CHARS] + "…"
        prompt += f"{idx + 1}) {text}\n"

    return prompt


# ---------------------------------------------------------------------------
# Soru çıkarma
# ---------------------------------------------------------------------------

def _extract_questions(raw_text: str) -> List[str]:
    """
    LLM çıktısından soru cümlelerini çıkarır.
    - Numaralı liste satırlarını temizler (1. / 1) vb.)
    - Sadece '?' ile biten cümleleri tutar
    - Başı/sonu boşluk temizlenir
    """
    lines = raw_text.strip().splitlines()
    questions = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Numaralı liste ön ekini kaldır: "1. ", "1) ", "- " vb.
        line = re.sub(r"^[\d]+[.)]\s*", "", line)
        line = re.sub(r"^[-*•]\s*", "", line)
        line = line.strip()
        if line.endswith("?") and len(line.split()) >= 4:
            questions.append(line)
    return questions


# ---------------------------------------------------------------------------
# Cosine similarity ile dedup
# ---------------------------------------------------------------------------

def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def _deduplicate_questions(
    questions: List[str],
    threshold: float = QUESTION_DEDUP_THRESHOLD,
    max_keep: int = MAX_QUESTIONS_PER_CLUSTER,
) -> List[str]:
    """
    Cosine similarity ile benzer soruları kaldırır.
    ChromaDB'nin DefaultEmbeddingFunction kullanılır (all-MiniLM-L6-v2).

    Args:
        questions : Soru listesi
        threshold : Bu değerin üzerinde benzerlik varsa duplicate sayılır
        max_keep  : Saklanacak max soru sayısı

    Returns:
        Benzersiz sorular listesi
    """
    if not questions:
        return []

    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        ef = DefaultEmbeddingFunction()
        embeddings = np.array(ef(questions), dtype=float)
    except Exception as exc:
        logger.warning("Could not compute embeddings, skipping dedup: %s", exc)
        return questions[:max_keep]

    kept_indices: List[int] = []
    kept_embeddings: List[np.ndarray] = []

    for i, emb in enumerate(embeddings):
        is_duplicate = False
        for kept_emb in kept_embeddings:
            if _cosine_sim(emb, kept_emb) >= threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            kept_indices.append(i)
            kept_embeddings.append(emb)
            if len(kept_indices) >= max_keep:
                break

    return [questions[i] for i in kept_indices]


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def generate_questions(
    clusters: Dict,
    event: str,
    country: str,
) -> Dict:
    """
    Her cluster için soru üretir.

    Args:
        clusters: clustering.run_clustering() çıktısı
                  {cluster_id: {cluster_articles, cluster_headline, metadata}}
        event   : Olay adı (RAG filtresi + prompt için)
        country : Ülke adı

    Returns:
        {
          cluster_id: {
            "cluster_headline": str,
            "question_sets"   : [[q1, q2, ...], [q1, q2, ...], [q1, q2, ...]],  # 3 run
            "all_questions"   : [q1, q2, ...],   # birleştirilmiş, ham
            "unique_questions": [q1, q2, ...],   # dedup sonrası
          }
        }
    """
    result: Dict = {}

    for cluster_id, cluster_data in clusters.items():
        headline = cluster_data["cluster_headline"]
        articles_texts = [a["text"] for a in cluster_data["cluster_articles"]]

        logger.info(
            "Cluster %s için soru üretiliyor: '%s' (%d makale)",
            cluster_id, headline, len(articles_texts),
        )

        prompt = _build_prompt(headline, articles_texts, event, country)

        # 3 bağımsız çalıştırma
        question_sets: List[List[str]] = []
        all_raw: List[str] = []

        for run_idx in range(QUESTION_RUNS_PER_CLUSTER):
            try:
                raw = llm_client.chat_simple(
                    user_prompt=prompt,
                    max_tokens=LLM_MAX_TOKENS_DEFAULT,
                    model=LLM_MODEL_QUESTIONS,
                    temperature=LLM_TEMPERATURE_QUESTIONS,
                )
                questions = _extract_questions(raw)
                question_sets.append(questions)
                all_raw.extend(questions)
                logger.debug(
                    "  Run %d/%d: %d soru üretildi",
                    run_idx + 1, QUESTION_RUNS_PER_CLUSTER, len(questions),
                )
            except Exception as exc:
                logger.error("  Run %d/%d failed: %s", run_idx + 1, QUESTION_RUNS_PER_CLUSTER, exc)
                question_sets.append([])

        # Dedup
        unique = _deduplicate_questions(all_raw)
        logger.info(
            "  Cluster %s: %d ham → %d benzersiz soru",
            cluster_id, len(all_raw), len(unique),
        )

        result[cluster_id] = {
            "cluster_headline": headline,
            "question_sets": question_sets,
            "all_questions": all_raw,
            "unique_questions": unique,
        }

    return result
