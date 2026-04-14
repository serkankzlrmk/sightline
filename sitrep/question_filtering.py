"""
sitrep_pipeline/question_filtering.py
4-kriter değerlendirme ile soru filtreleme.

Orijinal Stage 2.1 (2.1-Questions_filtering_SDGs.ipynb) mantığı.
SDG sınıflandırması kapsam dışı.
"""

import re
import json
import logging
from typing import List, Dict, Optional

from config import LLM_MAX_TOKENS_DEFAULT, LLM_MODEL_FILTER, LLM_TEMPERATURE_FILTER
import llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filtreleme prompt'u (orijinalden alındı)
# ---------------------------------------------------------------------------

_FILTER_PROMPT_TEMPLATE = """\
You are a strict evaluator of questions for humanitarian situational reports.

Evaluate the following question against exactly 4 criteria. Each criterion is a DISCARD criterion:

  1.  **Specific to Another Country:** Is the question explicitly specific to a country or region \
*other* than the one relevant to the report, in a way that makes it irrelevant or misleading for \
the current context?

  2.  **Too Political:** Does it focus heavily on political causes, express strong opinions, \
assign blame, propose political solutions or strategies, or exhibit bias instead of focusing \
on neutral humanitarian impact and response?

  3.  **Too Long-Term / Historical:** Does it focus on long-term historical analysis, \
root causes distant in time, or future speculation that is beyond the current situational \
snapshot? Questions about immediate impacts and current responses are acceptable.

  4.  **Too General / Too Specific:** Is it overly broad, abstract, or so micro-specific \
that it would not be answerable from a typical situational report? Even if the question is \
not related to the given country, it may still have an acceptable generality level.

  Each score should be evaluated independently from the others.

  Based strictly on these rules, respond with a JSON object in this format:
  {{
    "score": [0, 0, 0, 0],
    "reason": ["", "", "", ""]
  }}

  For the "score" array:
  - Provide a 0 if the question meets the corresponding discard criterion (i.e., it SHOULD be discarded).
  - Provide a 1 if the question does NOT meet the corresponding discard criterion (i.e., it is acceptable).

  For the "reason" array:
  - If a score for a criterion is 0, provide a brief explanation.
  - If a score for a criterion is 1, leave the string empty.

Question to evaluate:
{question}
"""


# ---------------------------------------------------------------------------
# Tek soru değerlendirmesi
# ---------------------------------------------------------------------------

def _evaluate_question(question: str) -> Optional[Dict]:
    """
    Tek bir soruyu 4 kriter üzerinden değerlendirir.

    Returns:
        {"score": [1,1,1,1], "reason": ["","","",""]}
        veya hata durumunda None
    """
    prompt = _FILTER_PROMPT_TEMPLATE.format(question=question)

    try:
        raw = llm_client.chat_simple(
            user_prompt=prompt,
            max_tokens=256,
            model=LLM_MODEL_FILTER,
            temperature=LLM_TEMPERATURE_FILTER,
        )
        # Markdown kod bloğunu temizle
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()

        # Model JSON'dan sonra açıklama eklemiş olabilir — sadece ilk { } bloğunu al
        match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not match:
            logger.warning("JSON not found | Response: %s", raw[:200])
            return None
        raw = match.group(0)

        result = json.loads(raw)

        score = result.get("score")
        if not isinstance(score, list) or len(score) != 4:
            logger.warning(
                "Soru değerlendirmesi geçersiz format: %s → %s", question[:60], score
            )
            return None

        return result

    except json.JSONDecodeError as exc:
        logger.warning("JSON parsing error: %s | Response: %s", exc, raw[:200])
        return None
    except Exception as exc:
        logger.error("Question evaluation error: %s", exc)
        return None


def _passes_all_criteria(eval_result: Dict) -> bool:
    """En fazla 1 kriter fail edebilir (kriter 1 = başka ülke kriteri hariç)."""
    score = eval_result.get("score", [0, 0, 0, 0])
    # Kriter 0 (başka ülke) kesin eleme — diğerlerinde en fazla 1 fail tolerans
    if score[0] == 0:
        return False
    fails = sum(1 for s in score[1:] if s == 0)
    return fails <= 1


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def filter_questions(questions_data: Dict) -> Dict:
    """
    Soru üretim çıktısını filtreler.

    Args:
        questions_data: question_generation.generate_questions() çıktısı
                        {cluster_id: {cluster_headline, unique_questions, ...}}

    Returns:
        {
          cluster_id: {
            "cluster_headline": str,
            "filtered_questions": [str, ...],   # 4 kriterin tümünü geçen sorular
            "total_evaluated"  : int,
            "total_passed"     : int,
          }
        }
    """
    result: Dict = {}

    for cluster_id, cluster_data in questions_data.items():
        headline = cluster_data["cluster_headline"]
        questions = cluster_data.get("unique_questions", [])

        logger.info(
            "Cluster %s filtreleniyor: '%s' (%d soru)",
            cluster_id, headline, len(questions),
        )

        filtered: List[str] = []
        evaluated = 0

        for question in questions:
            evaluated += 1
            eval_result = _evaluate_question(question)

            if eval_result is None:
                # Değerlendirme başarısız → güvenli tarafta kal, soruyu koru
                logger.debug("  Could not evaluate, keeping question: %s", question[:60])
                filtered.append(question)
                continue

            if _passes_all_criteria(eval_result):
                filtered.append(question)
                logger.debug("  PASSED: %s", question[:60])
            else:
                failed = [
                    i + 1
                    for i, s in enumerate(eval_result["score"])
                    if s == 0
                ]
                logger.info(
                    "  ELENDI (kriter %s | skor=%s): %s",
                    failed, eval_result["score"], question[:80],
                )

        logger.info(
            "  Cluster %s: %d değerlendirilen → %d geçti",
            cluster_id, evaluated, len(filtered),
        )

        result[cluster_id] = {
            "cluster_headline": headline,
            "filtered_questions": filtered,
            "total_evaluated": evaluated,
            "total_passed": len(filtered),
        }

    return result
