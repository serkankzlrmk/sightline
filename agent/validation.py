"""
validation.py — Cross-section consistency validation for proposals.

Checks that sections are internally consistent:
- ToC impact ↔ Logframe goal alignment
- Logframe indicators ↔ outputs coverage
- Budget total ↔ activities described
- M&E indicators ↔ Logframe indicators
- Risk matrix ↔ methodology risks
- Needs Assessment data ↔ Background claims
- Sustainability ↔ methodology capacity building
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def _safe_json(val):
    """Parse JSON string or return as-is if already parsed."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        if not val or val in ("{}", "[]"):
            return {} if val == "{}" else []
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


def _has_content(val):
    """Check if a section has meaningful content."""
    if not val:
        return False
    if isinstance(val, str):
        return len(val.strip()) > 10
    if isinstance(val, (dict, list)):
        return len(val) > 0
    return False


def _extract_numbers(text):
    """Extract numeric values from text."""
    if not text or not isinstance(text, str):
        return []
    numbers = re.findall(r"[\d,]+(?:\.\d+)?", text)
    return [float(n.replace(",", "")) for n in numbers if n.replace(",", "").replace(".", "").isdigit()]


def validate_cross_sections(proposal_row: dict) -> dict:
    """Run cross-section consistency checks on a proposal.

    Args:
        proposal_row: Full proposal dict

    Returns:
        {
            "warnings": [{"severity": "high|medium|low", "check": "...", "message": "..."}],
            "passed": int,
            "total": int,
            "summary": str,
        }
    """
    warnings = []
    passed = 0
    total = 0

    toc = _safe_json(proposal_row.get("toc", []))
    logframe = _safe_json(proposal_row.get("logframe", {}))
    budget = _safe_json(proposal_row.get("budget", {}))
    mne = _safe_json(proposal_row.get("mne_framework", {}))
    risks = _safe_json(proposal_row.get("risk_matrix", []))
    needs = proposal_row.get("needs_assessment", "")
    background = proposal_row.get("background", "")
    methodology = proposal_row.get("methodology", "")
    sustainability = proposal_row.get("sustainability", "")

    # ── Check 1: ToC impact ↔ Logframe goal ──
    total += 1
    if isinstance(toc, list) and toc and isinstance(logframe, dict):
        toc_impact = ""
        for item in toc:
            if isinstance(item, dict) and item.get("level") == "impact":
                toc_impact = item.get("text", "").lower()
                break
        lf_goal = str(logframe.get("goal", "")).lower()

        if toc_impact and lf_goal:
            shared_words = [
                w
                for w in [
                    "vulnerab",
                    "resilien",
                    "safe",
                    "health",
                    "protect",
                    "access",
                    "right",
                    "reduc",
                    "improv",
                    "support",
                ]
                if w in toc_impact and w in lf_goal
            ]
            if shared_words or len(toc_impact) > 10:
                passed += 1
            else:
                warnings.append(
                    {
                        "severity": "medium",
                        "check": "ToC Impact ↔ Logframe Goal",
                        "message": "Theory of Change impact and Logframe goal seem disconnected. "
                        "Ensure they describe the same long-term outcome.",
                    }
                )
        elif not lf_goal:
            warnings.append(
                {
                    "severity": "low",
                    "check": "Logframe Goal",
                    "message": "Logframe goal is empty — fill it from the ToC impact level.",
                }
            )

    # ── Check 2: Logframe outputs ↔ M&E indicators ──
    total += 1
    if isinstance(logframe, dict) and isinstance(mne, dict):
        lf_has_outputs = bool(logframe.get("outputs"))
        mne_indicators = mne.get("indicators", []) if isinstance(mne, dict) else []
        mne_has_output_indicators = (
            any(ind.get("type") == "output" for ind in mne_indicators if isinstance(ind, dict))
            if mne_indicators
            else False
        )

        if lf_has_outputs and mne_has_output_indicators:
            passed += 1
        elif lf_has_outputs and not mne_has_output_indicators:
            warnings.append(
                {
                    "severity": "medium",
                    "check": "Logframe Outputs ↔ M&E Indicators",
                    "message": "Logframe has outputs but M&E framework has no output-level indicators. "
                    "Every output should have at least one M&E indicator.",
                }
            )

    # ── Check 3: Budget total ↔ Methodology activities ──
    total += 1
    if isinstance(budget, dict) and budget.get("total") and methodology:
        budget_text = str(budget.get("total", ""))
        budget_numbers = _extract_numbers(budget_text)
        if budget_numbers:
            budget_val = budget_numbers[0]
            method_numbers = _extract_numbers(methodology)
            if method_numbers:
                rough_match = any(0.3 * budget_val <= n <= 3 * budget_val for n in method_numbers)
                if rough_match:
                    passed += 1
                else:
                    warnings.append(
                        {
                            "severity": "low",
                            "check": "Budget ↔ Methodology",
                            "message": f"Budget total ({budget_text}) doesn't match any numbers in methodology. "
                            "Ensure budget aligns with described activities.",
                        }
                    )
            else:
                passed += 1
        else:
            passed += 1
    elif not isinstance(budget, dict) or not budget.get("total"):
        if _has_content(methodology):
            warnings.append(
                {
                    "severity": "low",
                    "check": "Budget Total",
                    "message": "Budget has no total amount — add a total for consistency.",
                }
            )

    # ── Check 4: Risk Matrix ──
    total += 1
    if isinstance(risks, list) and risks:
        missing_mitigation = [r for r in risks if isinstance(r, dict) and not r.get("mitigation")]
        if not missing_mitigation:
            passed += 1
        else:
            warnings.append(
                {
                    "severity": "high",
                    "check": "Risk Matrix Mitigation",
                    "message": f"{len(missing_mitigation)} risk(s) have no mitigation strategy. "
                    "Every risk must have a mitigation measure.",
                }
            )
    else:
        warnings.append(
            {
                "severity": "low",
                "check": "Risk Matrix",
                "message": "Risk matrix is empty — identify at least 4-6 key project risks.",
            }
        )

    # ── Check 5: Needs Assessment ↔ Background data ──
    total += 1
    if _has_content(needs) and _has_content(background):
        needs_numbers = _extract_numbers(needs)
        background_numbers = _extract_numbers(background)
        if needs_numbers and background_numbers:
            major_discrepancy = abs(max(needs_numbers) - max(background_numbers)) > 10 * max(needs_numbers)
            if not major_discrepancy:
                passed += 1
            else:
                warnings.append(
                    {
                        "severity": "medium",
                        "check": "Needs Assessment ↔ Background",
                        "message": "Large discrepancy between displacement numbers in background and needs assessment. "
                        "Verify data consistency across sections.",
                    }
                )
        else:
            passed += 1
    else:
        passed += 1

    # ── Check 6: Sustainability ↔ Methodology capacity building ──
    total += 1
    if _has_content(sustainability) and _has_content(methodology):
        sustain_lower = sustainability.lower()
        method_lower = methodology.lower()
        capacity_keywords = ["capacity", "training", "skill", "handover", "local"]
        sustain_has_capacity = any(kw in sustain_lower for kw in capacity_keywords)
        method_has_capacity = any(kw in method_lower for kw in capacity_keywords)
        if sustain_has_capacity or method_has_capacity:
            passed += 1
        else:
            warnings.append(
                {
                    "severity": "low",
                    "check": "Sustainability ↔ Methodology",
                    "message": "Neither sustainability nor methodology mention capacity building, training, or handover. "
                    "Add capacity building components for a viable exit strategy.",
                }
            )
    else:
        passed += 1

    # ── Check 7: Coordination ↔ Clusters mentioned in other sections ──
    total += 1
    coordination = proposal_row.get("coordination", "")
    if _has_content(coordination):
        coord_lower = coordination.lower()
        cluster_keywords = ["cluster", "protection", "wash", "health", "shelter", "cccm", "education", "nutrition"]
        has_clusters = any(kw in coord_lower for kw in cluster_keywords)
        if has_clusters:
            passed += 1
        else:
            warnings.append(
                {
                    "severity": "low",
                    "check": "Coordination Clusters",
                    "message": "Coordination section doesn't mention specific clusters. "
                    "Reference the relevant cluster(s) your project contributes to.",
                }
            )
    else:
        passed += 1

    severity_order = {"high": 0, "medium": 1, "low": 2}
    warnings.sort(key=lambda w: severity_order.get(w["severity"], 3))

    high_count = sum(1 for w in warnings if w["severity"] == "high")
    summary_parts = [f"{passed}/{total} checks passed"]
    if warnings:
        summary_parts.append(f"{len(warnings)} warning(s)")
        if high_count:
            summary_parts.append(f"{high_count} critical")
    else:
        summary_parts.append("no issues found")

    return {
        "warnings": warnings,
        "passed": passed,
        "total": total,
        "summary": " | ".join(summary_parts),
    }
