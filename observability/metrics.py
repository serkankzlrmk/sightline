"""observability/metrics.py — deterministic answer-quality signals.

These are intentionally cheap, model-free and repeatable: they run on the hot
path (once per chat turn) and must never depend on network access. LLM-as-judge
scoring lives in the offline eval harness (scripts/eval_agent.py) instead.

Signals extracted here answer "did this turn actually produce a grounded
answer?" without needing a model:

- citation_count: number of distinct ``[n]`` citation markers in the answer.
- is_no_answer:  the agent said it could not find evidence.
- has_citation:   at least one inline citation marker exists.

Caveat: inline ``[n]`` markers only prove the model *tried* to cite. Semantic
citation validity (does source n actually support the claim) is Phase 2/3 work
and belongs to the offline judge, not this module.
"""

from __future__ import annotations

import re

_CITATION_RE = re.compile(r"\[(\d{1,3})\]")

# Conservative patterns: only explicit "I couldn't find evidence" phrasing.
_NO_ANSWER_PATTERNS = (
    "no clear answer",
    "sources do not contain",
    "sources don't contain",
    "do not contain enough information",
    "does not contain enough information",
    "insufficient information",
    "not enough information",
    "no information available",
    "no relevant information",
    "could not find any",
    "couldn't find any",
    "unable to find any",
    "no reports found",
    "no matching reports",
)


def extract_citations(text: str) -> list[int]:
    """Return citation numbers in order of appearance (duplicates preserved)."""
    if not text:
        return []
    return [int(m.group(1)) for m in _CITATION_RE.finditer(text)]


def citation_count(text: str) -> int:
    """Number of distinct citation numbers in the answer."""
    return len(set(extract_citations(text)))


def is_no_answer(text: str) -> bool:
    """True when the agent explicitly reports that evidence was not found."""
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in _NO_ANSWER_PATTERNS)


def answer_signals(text: str) -> dict:
    """Bundle the deterministic per-answer signals into one dict.

    Returned keys are stored directly on the ``turns`` row:
        citations, answer_chars, no_answer, has_citations
    """
    answer = text or ""
    citations = citation_count(answer)
    return {
        "citations": citations,
        "answer_chars": len(answer),
        "no_answer": is_no_answer(answer),
        "has_citations": citations > 0,
    }
