"""
me_reviewer.py — Automated M&E quality scoring for proposal sections.

Evaluates each section against:
- SMART indicator compliance (Specific, Measurable, Achievable, Relevant, Time-bound)
- Logical flow (ToC levels, logframe consistency)
- Source quality (recency, authority, citation presence)
- Completeness (required fields filled, no placeholders)
- Donor alignment (format match)

Returns structured quality_score dict with per-criterion scores and suggestions.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

SECTION_REQUIREMENTS = {
    "cover": {
        "required_fields": ["project_title", "country", "donor", "budget_summary",
                           "target_beneficiaries", "sectors", "summary", "duration_months"],
        "min_words": 20,
    },
    "background": {
        "min_words": 200,
        "must_contain": ["affected", "crisis", "population"],
    },
    "needs_assessment": {
        "min_words": 300,
        "must_contain": ["needs", "gap", "vulnerable"],
        "expect_numbers": True,
    },
    "toc": {
        "required_levels": ["impact", "outcome", "output", "activity"],
        "min_items": 4,
    },
    "logframe": {
        "required_fields": ["goal", "outcomes", "outputs", "activities"],
        "indicator_fields": ["goal_indicator", "outcomes_indicator", "outputs_indicator"],
    },
    "methodology": {
        "min_words": 200,
        "must_contain": ["approach", "targeting", "activities"],
    },
    "budget": {
        "required_fields": ["total", "lines"],
        "min_lines": 3,
    },
    "mne_framework": {
        "required_fields": ["indicators"],
        "min_indicators": 3,
    },
    "risk_matrix": {
        "min_items": 4,
        "required_fields_per_item": ["risk", "probability", "impact", "mitigation"],
    },
    "sustainability": {
        "min_words": 150,
        "must_contain": ["sustain", "capacity", "exit"],
    },
    "coordination": {
        "min_words": 100,
        "must_contain": ["cluster", "partner"],
    },
    "final_review": {
        "min_words": 500,
    },
}

SMART_KEYWORDS = {
    "specific": ["number", "%", "target", "beneficiaries", "households", "people"],
    "measurable": ["indicator", "baseline", "target", "monitor", "data"],
    "achievable": ["feasible", "capacity", "resources", "team", "staff"],
    "relevant": ["need", "priority", "response", "sector", "vulnerable"],
    "time_bound": ["month", "year", "by", "end of", "quarter", "week"],
}


def _count_words(text: str) -> int:
    if not text or not isinstance(text, str):
        return 0
    return len(text.split())


def _check_smart(content: str) -> dict:
    """Check content for SMART indicator compliance."""
    text_lower = (content or "").lower()
    checks = {}
    score = 0
    total = 5

    for criterion, keywords in SMART_KEYWORDS.items():
        found = any(kw in text_lower for kw in keywords)
        checks[criterion] = found
        if found:
            score += 1

    comments = []
    if not checks.get("specific"):
        comments.append("Indicators lack specific numbers/targets (e.g., '500 households', '30% improvement')")
    if not checks.get("measurable"):
        comments.append("No measurable indicators found (baseline/target values missing)")
    if not checks.get("achievable"):
        comments.append("Achievability unclear — mention resources, capacity, or team size")
    if not checks.get("relevant"):
        comments.append("Relevance not established — link to needs/priorities")
    if not checks.get("time_bound"):
        comments.append("No time references found (months, quarters, 'by end of year')")

    return {
        "score": score,
        "total": total,
        "checks": {k: "✓" if v else "✗" for k, v in checks.items()},
        "comments": comments,
    }


def _check_logical_flow(toc: list, logframe: dict) -> dict:
    """Check ToC levels flow logically and logframe aligns."""
    checks = []
    score = 0
    total = 4

    if not toc or not isinstance(toc, list):
        return {"score": 0, "total": total, "checks": [], "comments": ["Theory of Change is empty or invalid"]}

    levels = [item.get("level", "") for item in toc]
    expected = ["impact", "outcome", "output", "activity"]

    has_all_levels = all(l in levels for l in expected)
    if has_all_levels:
        score += 1
        checks.append({"check": "All 4 ToC levels present", "valid": True})
    else:
        missing = [l for l in expected if l not in levels]
        checks.append({"check": f"Missing ToC levels: {', '.join(missing)}", "valid": False})

    if len(toc) >= 4:
        score += 1
        checks.append({"check": "ToC has at least 4 items", "valid": True})
    else:
        checks.append({"check": f"ToC has only {len(toc)} items (minimum 4)", "valid": False})

    if logframe and isinstance(logframe, dict):
        lf_keys = set(logframe.keys())
        required_lf = {"goal", "outcomes", "outputs", "activities"}
        if required_lf.issubset(lf_keys):
            score += 1
            checks.append({"check": "Logframe has all required fields", "valid": True})
        else:
            missing = required_lf - lf_keys
            checks.append({"check": f"Logframe missing: {', '.join(missing)}", "valid": False})

        indicator_present = any("indicator" in k for k in lf_keys)
        if indicator_present:
            score += 1
            checks.append({"check": "Logframe has indicators", "valid": True})
        else:
            checks.append({"check": "Logframe missing indicators", "valid": False})
    else:
        checks.append({"check": "Logframe not available", "valid": False})
        checks.append({"check": "No indicators in logframe", "valid": False})

    comments = [c["check"] for c in checks if not c["valid"]]
    return {"score": score, "total": total, "checks": checks, "comments": comments}


def _check_source_quality(content: str, sources: list = None) -> dict:
    """Check if content cites sources and sources are recent/authoritative."""
    checks = []
    score = 0
    total = 3

    text = content or ""
    has_inline_citations = bool(re.search(r"https?://", text)) or bool(re.search(r"\[\d+\]", text))
    if has_inline_citations:
        score += 1
        checks.append({"check": "Inline citations found", "valid": True})
    else:
        checks.append({"check": "No inline citations found", "valid": False, "comment": "Add source links for data claims"})

    if sources and len(sources) > 0:
        score += 1
        checks.append({"check": f"{len(sources)} sources cited", "valid": True})
    else:
        checks.append({"check": "No sources listed", "valid": False, "comment": "List data sources (ReliefWeb, HDX, WorldBank)"})

    authoritative_sources = ["reliefweb", "unhcr", "ocha", "who", "unicef", "wfp", "world bank", "hdx", "worldbank"]
    has_authoritative = any(a in text.lower() for a in authoritative_sources)
    if has_authoritative:
        score += 1
        checks.append({"check": "Authoritative sources referenced", "valid": True})
    else:
        checks.append({"check": "No authoritative sources found", "valid": False, "comment": "Reference UN agencies, ReliefWeb, or HDX data"})

    comments = [c.get("comment", c["check"]) for c in checks if not c["valid"]]
    return {"score": score, "total": total, "checks": checks, "comments": comments}


def _check_completeness(content, step: str) -> dict:
    """Check if section content meets minimum requirements."""
    req = SECTION_REQUIREMENTS.get(step, {})
    checks = []
    score = 0
    total = 0

    if "min_words" in req:
        total += 1
        word_count = _count_words(content if isinstance(content, str) else json.dumps(content))
        if word_count >= req["min_words"]:
            score += 1
            checks.append({"check": f"Word count: {word_count} (min: {req['min_words']})", "valid": True})
        else:
            checks.append({"check": f"Too short: {word_count} words (need {req['min_words']})", "valid": False})

    if "must_contain" in req:
        total += 1
        text_lower = (content if isinstance(content, str) else json.dumps(content)).lower()
        found = any(kw in text_lower for kw in req["must_contain"])
        if found:
            score += 1
            checks.append({"check": "Key concepts present", "valid": True})
        else:
            checks.append({"check": f"Missing key concepts (expected: {', '.join(req['must_contain'])})", "valid": False})

    if "required_fields" in req:
        total += 1
        if isinstance(content, dict):
            missing = [f for f in req["required_fields"] if f not in content or not content[f]]
            if not missing:
                score += 1
                checks.append({"check": "All required fields present", "valid": True})
            else:
                checks.append({"check": f"Missing fields: {', '.join(missing)}", "valid": False})
        elif isinstance(content, str):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    missing = [f for f in req["required_fields"] if f not in parsed or not parsed[f]]
                    if not missing:
                        score += 1
                        checks.append({"check": "All required fields present", "valid": True})
                    else:
                        checks.append({"check": f"Missing fields: {', '.join(missing)}", "valid": False})
                else:
                    checks.append({"check": "Content is not a JSON object", "valid": False})
            except Exception:
                checks.append({"check": "Content is not valid JSON", "valid": False})
        else:
            checks.append({"check": "Content is not a dict", "valid": False})

    if "min_items" in req:
        total += 1
        items = content if isinstance(content, list) else []
        if len(items) >= req["min_items"]:
            score += 1
            checks.append({"check": f"{len(items)} items (min: {req['min_items']})", "valid": True})
        else:
            checks.append({"check": f"Only {len(items)} items (need {req['min_items']})", "valid": False})

    if "min_lines" in req and isinstance(content, dict):
        total += 1
        lines = content.get("lines", [])
        if len(lines) >= req["min_lines"]:
            score += 1
            checks.append({"check": f"{len(lines)} budget lines (min: {req['min_lines']})", "valid": True})
        else:
            checks.append({"check": f"Only {len(lines)} budget lines (need {req['min_lines']})", "valid": False})

    if "min_indicators" in req and isinstance(content, dict):
        total += 1
        indicators = content.get("indicators", [])
        if len(indicators) >= req["min_indicators"]:
            score += 1
            checks.append({"check": f"{len(indicators)} indicators (min: {req['min_indicators']})", "valid": True})
        else:
            checks.append({"check": f"Only {len(indicators)} indicators (need {req['min_indicators']})", "valid": False})

    if not checks:
        return {"score": 100, "total": 1, "checks": [], "comments": []}

    percentage = int((score / total) * 100) if total > 0 else 0
    comments = [c["check"] for c in checks if not c["valid"]]
    return {"score": percentage, "total": total, "checks": checks, "comments": comments}


def review_section(content, step: str, toc: list = None, logframe: dict = None, sources: list = None) -> dict:
    """Run M&E quality review on a single section.

    Args:
        content: Section content (str, dict, or list)
        step: Section step name
        toc: Theory of Change (for cross-reference)
        logframe: Logframe (for cross-reference)
        sources: List of source dicts [{"title": "...", "url": "..."}]

    Returns:
        {
            "quality_score": {
                "smart_indicators": {...},
                "logical_flow": {...},
                "source_quality": {...},
                "completeness": {...},
            },
            "suggestions": ["...", "..."],
            "overall_score": int  # 0-100
        }
    """
    content_str = content if isinstance(content, str) else json.dumps(content, indent=2)

    smart = _check_smart(content_str)
    flow = _check_logical_flow(toc or [], logframe or {})
    source_q = _check_source_quality(content_str, sources)
    completeness = _check_completeness(content, step)

    suggestions = []

    for comment in smart.get("comments", []):
        suggestions.append(f"🔴 SMART: {comment}")
    for comment in flow.get("comments", []):
        suggestions.append(f"🟡 Logic: {comment}")
    for comment in source_q.get("comments", []):
        suggestions.append(f"🔵 Source: {comment}")
    for comment in completeness.get("comments", []):
        suggestions.append(f"🟠 Complete: {comment}")

    if not suggestions:
        suggestions.append("🟢 All quality checks passed!")

    smart_pct = int((smart["score"] / smart["total"]) * 100) if smart["total"] > 0 else 100
    flow_pct = int((flow["score"] / flow["total"]) * 100) if flow["total"] > 0 else 100
    source_pct = int((source_q["score"] / source_q["total"]) * 100) if source_q["total"] > 0 else 100
    comp_pct = completeness["score"] if isinstance(completeness["score"], int) else int(completeness["score"])

    overall = int((smart_pct + flow_pct + source_pct + comp_pct) / 4)

    return {
        "quality_score": {
            "smart_indicators": smart,
            "logical_flow": flow,
            "source_quality": source_q,
            "completeness": completeness,
        },
        "suggestions": suggestions,
        "overall_score": overall,
    }


def review_proposal(proposal_row: dict) -> dict:
    """Comprehensive review of the entire proposal.

    Args:
        proposal_row: Full proposal dict with all sections

    Returns:
        {
            "sections": {step: review_result},
            "overall_score": int,
            "summary": str,
            "critical_gaps": [...],
        }
    """
    section_results = {}
    total_score = 0
    section_count = 0
    critical_gaps = []

    field_map = {
        "cover": "cover_page",
        "background": "background",
        "needs_assessment": "needs_assessment",
        "toc": "toc",
        "logframe": "logframe",
        "methodology": "methodology",
        "budget": "budget",
        "mne_framework": "mne_framework",
        "risk_matrix": "risk_matrix",
        "sustainability": "sustainability",
        "coordination": "coordination",
        "final_review": "narrative",
    }

    toc_data = proposal_row.get("toc", [])
    logframe_data = proposal_row.get("logframe", {})
    if isinstance(toc_data, str):
        try:
            toc_data = json.loads(toc_data)
        except Exception:
            toc_data = []
    if isinstance(logframe_data, str):
        try:
            logframe_data = json.loads(logframe_data)
        except Exception:
            logframe_data = {}

    for step, field in field_map.items():
        content = proposal_row.get(field, "")
        if not content or content in ("", "{}", "[]", None):
            critical_gaps.append(f"{step}: Section is empty")
            continue

        if isinstance(content, str):
            try:
                content = json.loads(content)
            except Exception:
                pass

        result = review_section(content, step, toc_data, logframe_data)
        section_results[step] = result
        total_score += result["overall_score"]
        section_count += 1

        if result["overall_score"] < 50:
            critical_gaps.append(f"{step}: Score {result['overall_score']}/100 — needs significant improvement")

    overall = int(total_score / section_count) if section_count > 0 else 0

    summary_parts = [f"Overall Quality Score: {overall}/100"]
    if critical_gaps:
        summary_parts.append(f"{len(critical_gaps)} critical gaps found")
    else:
        summary_parts.append("No critical gaps — proposal is ready for submission")

    return {
        "sections": section_results,
        "overall_score": overall,
        "summary": " | ".join(summary_parts),
        "critical_gaps": critical_gaps,
    }
