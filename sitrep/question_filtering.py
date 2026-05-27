"""
sitrep_pipeline/question_filtering.py
Question filtering via 4-criteria evaluation.

Original Stage 2.1 (2.1-Questions_filtering_SDGs.ipynb) logic.
SDG classification is out of scope.
"""

import re
import json
import logging
from typing import List, Dict, Optional

from config import LLM_MAX_TOKENS_DEFAULT, LLM_MODEL_FILTER, LLM_TEMPERATURE_FILTER
import llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filtering prompt (taken from original)
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
# Single question evaluation
# ---------------------------------------------------------------------------

def _evaluate_question(question: str) -> Optional[Dict]:
    """
    Evaluates a single question against 4 criteria.

    Returns:
        {"score": [1,1,1,1], "reason": ["","","",""]}
        or None on error
    """
    prompt = _FILTER_PROMPT_TEMPLATE.format(question=question)

    try:
        raw = llm_client.chat_simple(
            user_prompt=prompt,
            max_tokens=256,
            model=LLM_MODEL_FILTER,
            temperature=LLM_TEMPERATURE_FILTER,
        )
        # Clean markdown code block
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()

        # Model may have added explanation after JSON — take only the first { } block
        match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not match:
            logger.warning("JSON not found | Response: %s", raw[:200])
            return None
        raw = match.group(0)

        result = json.loads(raw)

        score = result.get("score")
        if not isinstance(score, list) or len(score) != 4:
            logger.warning(
                "Invalid question evaluation format: %s → %s", question[:60], score
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
    """At most 1 criterion can fail (criterion 1 = other-country criterion excluded)."""
    score = eval_result.get("score", [0, 0, 0, 0])
    # Criterion 0 (other country) is a hard reject — others allow at most 1 fail tolerance
    if score[0] == 0:
        return False
    fails = sum(1 for s in score[1:] if s == 0)
    return fails <= 1


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def filter_questions(questions_data: Dict) -> Dict:
    """
    Filters question generation output.

    Args:
        questions_data: Output of question_generation.generate_questions()
                        {cluster_id: {cluster_headline, unique_questions, ...}}

    Returns:
        {
          cluster_id: {
            "cluster_headline": str,
            "filtered_questions": [str, ...],   # questions passing all 4 criteria
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
            "Filtering cluster %s: '%s' (%d questions)",
            cluster_id, headline, len(questions),
        )

        filtered: List[str] = []
        evaluated = 0

        for question in questions:
            evaluated += 1
            eval_result = _evaluate_question(question)

            if eval_result is None:
                # Evaluation failed → stay safe, keep the question
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
                    "  REJECTED (criterion %s | score=%s): %s",
                    failed, eval_result["score"], question[:80],
                )

        logger.info(
            "  Cluster %s: %d evaluated → %d passed",
            cluster_id, evaluated, len(filtered),
        )

        result[cluster_id] = {
            "cluster_headline": headline,
            "filtered_questions": filtered,
            "total_evaluated": evaluated,
            "total_passed": len(filtered),
        }

    return result
