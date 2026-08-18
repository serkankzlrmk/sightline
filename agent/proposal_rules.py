"""Deterministic rules for the Guided Proposal .

This module contains no model calls. It is the stable, auditable rules layer
that runs before the blind-verifier agent. All donor-specific constraints are
driven by the DONOR_PROFILES manifest — no hardcoded if-else per donor.
"""

from __future__ import annotations

from typing import Any

# ── Global constants (used as fallbacks) ────────────────────────────────────
STEP2_NARRATIVE_FIELDS = ("humanitarian_context", "needs_assessment", "strategic_justification")
BENEFICIARY_CATEGORIES = ("host_communities", "idps", "refugees_returnees")
BENEFICIARY_DEMOGRAPHICS = (
    "men_18_59",
    "women_18_59",
    "boys_0_17",
    "girls_0_17",
    "elderly_60_plus",
    "persons_with_disabilities",
)
LOGFRAME_LEVELS = ("impact", "outcome", "output", "activity")
DEFAULT_MAX_CHARS = 4000
DEFAULT_INTENT_MIN = 100
DEFAULT_INTENT_MAX = 500


# ── Donor manifest (version 2.0.0-2026) ─────────────────────────────────────
DONOR_PROFILES = {
    "ocha_cbpf": {
        "id": "ocha_cbpf",
        "label": "OCHA CBPF",
        "full_name": "UN OCHA Country-Based Pooled Fund",
        "framework_standard": "GPPi 8+3 Humanitarian Standard",
        "overhead_ceiling_percent": 7.0,
        "max_duration_months": 12,
        "currency_options": ["USD"],
        "step_1_advisories": [
            "State how gender, age, and disability are considered in the project intent.",
            "Use a concise, geographically specific project title.",
            "Must align with current HRP (Humanitarian Response Plan) strategic objectives.",
            "Must reference cluster coordination mechanisms.",
            "Programme support costs must not exceed 7%.",
            "CBPF gender marker code required (0-2).",
        ],
        "budget_categories": [
            "Staff & Personnel",
            "Supplies & Commodities",
            "Equipment",
            "Contractual Services",
            "Transport & Storage",
            "General Operating & Support Costs",
            "Sub-Grants",
            "Programme Support (max 7%)",
        ],
        "indicator_format": "Indicators must align with HRP (Humanitarian Response Plan) indicators. Each indicator: result statement, unit of measure, baseline, target, disaggregation, data source, frequency.",
        "special_requirements": [
            "Must align with current HRP strategic objectives",
            "Must reference cluster strategic objectives",
            "Programme support costs must not exceed 7%",
            "Must include AAP (Accountability to Affected Populations) measures",
            "Maximum project duration 12 months (exceptional 24 months)",
            "CBPF gender marker code required (0-2)",
        ],
        "section_rules": {
            "step1_executive_intent": {
                "min_characters": 100,
                "max_characters": 500,
                "mandatory_tokens": ["humanitarian", "target"],
                "rationale": "OCHA GMS database fields strictly enforce character constraints.",
            },
            "step2_humanitarian_context": {
                "max_characters": 4000,
                "mandatory_tokens": ["crisis", "displacement", "conflict"],
                "rationale": "Context must cite specific localized crisis triggers.",
            },
            "step2_needs_assessment": {
                "max_characters": 4000,
                "mandatory_tokens": ["gender", "disability", "protection"],
                "rationale": "OCHA requires explicit Gender and Age Marker (GAM) alignment and PwD analysis.",
            },
            "step2_strategic_justification": {
                "max_characters": 4000,
                "mandatory_tokens": ["presence", "capacity", "added value"],
                "rationale": "CSOs must demonstrate direct field presence in operational zones.",
            },
        },
        "beneficiary_rules": {
            "disaggregation_required": True,
            "min_vulnerable_quota_percent": 0.0,
            "rationale": "OCHA mandates complete 3x6 demographic breakdowns for all targeting tables.",
        },
        "logframe_rules": {
            "max_outcomes": 3,
            "mandatory_levels": ["impact", "outcome", "output", "activity"],
            "require_hrp_alignment": True,
            "rationale": "Logframes must mirror the relevant Humanitarian Response Plan (HRP) sector indicators.",
        },
        "financial_rules": {
            "max_overhead_category5_percent": 7.0,
            "psea_mandatory_signoff": True,
            "sphere_standards_required": True,
            "localization_min_subgrant_recommendation_percent": 15.0,
            "rationale": "UN Financial Regulations enforce a strict 7% ceiling on Category 5 Indirect Support Costs.",
        },
        "prompt_directive": "Enforce GPPi 8+3 layout structure. Ensure GBV referral pathways, AAP (Accountability to Affected Populations), and GAM Marker inclusion strategies are explicitly stated in narrative outputs. Align project objectives with HRP strategic objectives. Reference cluster coordination mechanisms. Budget: Programme support costs must not exceed 7%. Gender marker code required (0-2). Maximum 12-month duration.",
    },
    "usaid_bha": {
        "id": "usaid_bha",
        "label": "USAID/BHA",
        "full_name": "U.S. Agency for International Development / Bureau for Humanitarian Assistance",
        "framework_standard": "USAID BHA Emergency Application Guidelines",
        "overhead_ceiling_percent": 10.0,
        "max_duration_months": 24,
        "currency_options": ["USD"],
        "step_1_advisories": [
            "Identify the crisis-affected population the intervention will target.",
            "PSEA, Sphere, and sector-specific compliance checks are collected in later steps.",
            "Disability inclusion must be addressed (Washington Group Questions).",
            "Gender analysis must be included in needs assessment.",
            "Safeguarding policy must be referenced.",
            "Indirect rate based on NICRA or 10% de minimis if no NICRA.",
        ],
        "budget_categories": [
            "Personnel (US & Local)",
            "Fringe Benefits",
            "Travel",
            "Equipment",
            "Supplies & Commodities",
            "Contractual",
            "Construction",
            "Other Direct Costs",
            "Sub-Grants",
            "Indirect Charges (NICRA or 10% de minimis)",
        ],
        "indicator_format": "Indicators must be output or outcome level, include: definition, unit of measure, baseline, target, disaggregation (sex, age, disability if relevant), data source, frequency, responsible party.",
        "special_requirements": [
            "Disability inclusion must be addressed (Washington Group Questions)",
            "Gender analysis must be included in needs assessment",
            "Safeguarding policy must be referenced",
            "Indirect rate based on NICRA or 10% de minimis if no NICRA",
            "Sub-grants require sub-recipient risk assessment",
            "MEAL plan with learning component required",
        ],
        "section_rules": {
            "step1_executive_intent": {
                "min_characters": 100,
                "max_characters": 500,
                "mandatory_tokens": ["bha", "emergency"],
                "rationale": "BHA pre-screening filters proposals by strategic emergency scope.",
            },
            "step2_humanitarian_context": {
                "max_characters": 4000,
                "mandatory_tokens": ["humanity", "neutrality", "impartiality", "operational independence"],
                "rationale": "Proposals must explicitly state adherence to core Humanitarian Principles during risk screening.",
            },
            "step2_needs_assessment": {
                "max_characters": 4000,
                "mandatory_tokens": ["vulnerability", "protection", "risk"],
                "rationale": "Needs assessments require detailed sectoral vulnerability analyses.",
            },
            "step2_strategic_justification": {
                "max_characters": 4000,
                "mandatory_tokens": ["coordination", "cluster", "complementarity"],
                "rationale": "BHA requires evidence of active participation in the UN Cluster Coordination system.",
            },
        },
        "beneficiary_rules": {
            "disaggregation_required": True,
            "min_vulnerable_quota_percent": 50.0,
            "rationale": "At least 50% of targeted beneficiaries MUST be refugees, IDPs, or conflict-affected individuals.",
        },
        "logframe_rules": {
            "max_outcomes": 3,
            "mandatory_levels": ["impact", "outcome", "output", "activity"],
            "custom_indicator_itt_pirs_required": True,
            "rationale": "Custom indicators must include explicit ITT and PIRS metadata per BHA Indicator Handbook.",
        },
        "financial_rules": {
            "max_overhead_category5_percent": 10.0,
            "psea_mandatory_signoff": True,
            "sphere_standards_required": True,
            "equipment_capitalization_threshold_usd": 5000.0,
            "rationale": "Items with unit cost >= $5,000 must be flagged for USAID inventory property tracking.",
        },
        "prompt_directive": "Incorporate Washington Group disability questions criteria. Ensure explicit mentions of Humanitarian Principles and BHA sector indicators. Use Results Framework terminology. Budget must use BHA cost categories. Indirect costs based on NICRA or 10% de minimis. Include disability inclusion strategy. Include gender analysis and safeguarding measures. MEAL plan must include learning component. Indicators must include disaggregation by sex, age, and disability where relevant.",
    },
    "europeaid_prag": {
        "id": "europeaid_prag",
        "label": "EuropeAid (PRAG)",
        "full_name": "EuropeAid PRAG (Practical Guide)",
        "framework_standard": "Practical Guide to Contract Procedures for EU External Actions",
        "overhead_ceiling_percent": 7.0,
        "max_duration_months": 36,
        "currency_options": ["EUR"],
        "step_1_advisories": [
            "Use a title that clearly connects the action, location, and intended population.",
            "PRAG technical and financial scoring is applied in later steps.",
            "Address regional call priorities and local partner involvement.",
        ],
        "budget_categories": [
            "Staff & International Experts",
            "Local Staff",
            "Travel & Per Diem",
            "Equipment & Supplies",
            "Drugs & Medical Supplies",
            "Food & Nutrition",
            "WASH Materials",
            "Shelter Materials",
            "Transport & Logistics",
            "Training & Capacity Building",
            "Monitoring & Evaluation",
            "Communications & Visibility",
            "Office & Administration",
            "Indirect Costs (max 7%)",
        ],
        "indicator_format": "Each indicator must specify: description, baseline value, target value, source of verification, frequency of data collection, responsible person.",
        "special_requirements": [
            "Indirect costs must not exceed 7% of total budget",
            "Must address regional call priorities",
            "Must demonstrate local partner involvement",
            "Gender marker code (0, 1, or 2) must be specified",
        ],
        "section_rules": {
            "step1_executive_intent": {
                "min_characters": 100,
                "max_characters": 500,
                "mandatory_tokens": ["prag", "objective"],
                "rationale": "PRAG calls require immediate alignment with Lot and Specific Objectives.",
            },
            "step2_humanitarian_context": {
                "max_characters": 4000,
                "mandatory_tokens": ["regional", "policy", "alignment"],
                "rationale": "Must demonstrate alignment with EU regional priorities and strategies.",
            },
            "step2_needs_assessment": {
                "max_characters": 4000,
                "mandatory_tokens": ["stakeholder", "target group", "final beneficiaries"],
                "rationale": "PRAG strictly distinguishes between Target Groups and Final Beneficiaries.",
            },
            "step2_strategic_justification": {
                "max_characters": 4000,
                "mandatory_tokens": ["priority", "local partner", "sustainability"],
                "rationale": "Must explicitly address local partner involvement and long-term sustainability.",
            },
        },
        "beneficiary_rules": {
            "disaggregation_required": True,
            "min_vulnerable_quota_percent": 0.0,
            "rationale": "Requires structured target group tables aligned with PADOR organization filings.",
        },
        "logframe_rules": {
            "max_outcomes": 3,
            "mandatory_levels": ["impact", "outcome", "output", "activity"],
            "quarterly_activity_milestones_required": True,
            "rationale": "Activities must have concrete quarterly milestones mapped in the work plan.",
        },
        "financial_rules": {
            "max_overhead_category5_percent": 7.0,
            "psea_mandatory_signoff": True,
            "sphere_standards_required": True,
            "prag_capacity_threshold": 12.0,
            "prag_hard_fail_subscore": 1.0,
            "commercial_formula": "P_m = 25 * (C_min / C_proposed)",
            "rationale": "Evaluated using standard PRAG 12/20 capacity score thresholds and commercial weighted formulas.",
        },
        "prompt_directive": "Adhere strictly to PRAG Grant Contract templates. Ensure clear distinction between target groups, final beneficiaries, and local CSOs. Address regional call priorities explicitly. Demonstrate local partner involvement. Budget: Indirect costs must not exceed 7%. Include gender marker assessment (0=no gender, 1=gender mainstreamed, 2=gender transformative). Indicators must follow PRAG methodology: baseline -> target -> source -> frequency.",
    },
    "echo": {
        "id": "echo",
        "label": "ECHO",
        "full_name": "European Civil Protection and Humanitarian Aid Operations",
        "framework_standard": "ECHO Single Form Standard",
        "overhead_ceiling_percent": 7.0,
        "max_duration_months": 24,
        "currency_options": ["EUR"],
        "step_1_advisories": [
            "Follow ECHO HIP (Humanitarian Implementation Plan) format.",
            "Gender marker code (0, 1, or 2) must be specified.",
            "Climate change marker if applicable.",
            "Resilience marker if applicable.",
            "Maximum 7% indirect costs.",
        ],
        "budget_categories": [
            "Staff & International Experts",
            "Local Staff",
            "Travel & Per Diem",
            "Equipment & Supplies",
            "Drugs & Medical Supplies",
            "Food & Nutrition",
            "WASH Materials",
            "Shelter Materials",
            "Transport & Logistics",
            "Training & Capacity Building",
            "Monitoring & Evaluation",
            "Communications & Visibility",
            "Office & Administration",
            "Indirect Costs (max 7%)",
        ],
        "indicator_format": "Each indicator must specify: description, baseline value, target value, source of verification, frequency of data collection, responsible person.",
        "special_requirements": [
            "Gender marker code (0, 1, or 2) must be specified",
            "Climate change marker if applicable",
            "Resilience marker if applicable",
            "Maximum 7% indirect costs",
            "Cash-based interventions must follow ECHO Cash Guidance Note",
        ],
        "section_rules": {
            "step1_executive_intent": {
                "min_characters": 100,
                "max_characters": 500,
                "mandatory_tokens": ["echo", "humanitarian"],
                "rationale": "ECHO HIP requires immediate identification with the humanitarian aid framework.",
            },
            "step2_humanitarian_context": {
                "max_characters": 4000,
                "mandatory_tokens": ["hip", "crisis", "needs"],
                "rationale": "Context must reference the relevant ECHO HIP document and crisis specifics.",
            },
            "step2_needs_assessment": {
                "max_characters": 4000,
                "mandatory_tokens": ["protection", "gender", "resilience"],
                "rationale": "ECHO requires protection mainstreaming, gender analysis and resilience integration.",
            },
            "step2_strategic_justification": {
                "max_characters": 4000,
                "mandatory_tokens": ["presence", "capacity"],
                "rationale": "ECHO requires demonstrated operational presence and capacity.",
            },
        },
        "beneficiary_rules": {
            "disaggregation_required": True,
            "min_vulnerable_quota_percent": 0.0,
            "rationale": "ECHO Single Form requires complete beneficiary disaggregation.",
        },
        "logframe_rules": {
            "max_outcomes": 3,
            "mandatory_levels": ["impact", "outcome", "output", "activity"],
            "rationale": "ECHO requires a standard four-tier logical framework hierarchy.",
        },
        "financial_rules": {
            "max_overhead_category5_percent": 7.0,
            "psea_mandatory_signoff": True,
            "sphere_standards_required": True,
            "rationale": "ECHO enforces a 7% ceiling on indirect costs per Single Form guidelines.",
        },
        "prompt_directive": "Incorporate ECHO Gender-Age Marker and Climate/Resilience Marker criteria in narrative synthesis. Section headings must match ECHO template. Budget must use ECHO cost categories. Indirect costs must not exceed 7%. Reference ECHO HIP thematic priorities for the country. Indicators must follow ECHO methodology: baseline -> target -> source -> frequency.",
    },
    "unfpa": {
        "id": "unfpa",
        "label": "UNFPA",
        "full_name": "United Nations Population Fund",
        "framework_standard": "UNFPA GBV & SRHR Emergency Guidelines",
        "overhead_ceiling_percent": 7.0,
        "max_duration_months": 12,
        "currency_options": ["USD"],
        "step_1_advisories": [
            "State the protection, gender equality and safeguarding outcome clearly.",
            "Identify women, girls and other groups facing heightened vulnerability.",
            "Describe the local coordination and referral pathway the action will strengthen.",
        ],
        "budget_categories": [
            "Personnel",
            "Training & Capacity Building",
            "Community Activities",
            "Referral Services",
            "Monitoring & Evaluation",
            "Operations & Administration",
        ],
        "indicator_format": "Indicators must state a baseline, target, source of verification, frequency and sex-age disaggregation where relevant.",
        "special_requirements": [
            "Apply survivor-centred safeguarding principles",
            "Include gender and age-sensitive targeting",
            "Demonstrate local CSO and municipality coordination",
        ],
        "section_rules": {
            "step1_executive_intent": {
                "min_characters": 100,
                "max_characters": 500,
                "mandatory_tokens": ["srhr", "gbv"],
                "rationale": "UNFPA requires explicit SRHR and GBV outcome framing in project intent.",
            },
            "step2_humanitarian_context": {
                "max_characters": 4000,
                "mandatory_tokens": ["displacement", "protection"],
                "rationale": "Context must address displacement-driven protection risks for women and girls.",
            },
            "step2_needs_assessment": {
                "max_characters": 4000,
                "mandatory_tokens": ["survivor", "dignity", "maternal"],
                "rationale": "UNFPA needs assessments must centre survivor dignity and maternal health.",
            },
            "step2_strategic_justification": {
                "max_characters": 4000,
                "mandatory_tokens": ["coordination", "cso"],
                "rationale": "UNFPA requires evidence of CSO coordination and referral pathway strengthening.",
            },
        },
        "beneficiary_rules": {
            "disaggregation_required": True,
            "min_vulnerable_quota_percent": 0.0,
            "rationale": "UNFPA requires sex and age disaggregated beneficiary data.",
        },
        "logframe_rules": {
            "max_outcomes": 3,
            "mandatory_levels": ["impact", "outcome", "output", "activity"],
            "rationale": "UNFPA follows standard four-tier logframe with protection outcome focus.",
        },
        "financial_rules": {
            "max_overhead_category5_percent": 7.0,
            "psea_mandatory_signoff": True,
            "sphere_standards_required": True,
            "rationale": "UNFPA financial rules cap indirect costs at 7%.",
        },
        "prompt_directive": "Emphasize survivor-centred approaches, GBV minimum standards, and SRHR service integration. Centre women, girls and groups facing heightened protection risks. Apply survivor-centred safeguarding and safe referral principles. Strengthen local CSO and municipality coordination. Use indicators disaggregated by sex and age where relevant.",
    },
    "generic": {
        "id": "generic",
        "label": "Generic Donor",
        "full_name": "Standard humanitarian proposal format",
        "framework_standard": "Standard International Grant Framework",
        "overhead_ceiling_percent": 10.0,
        "max_duration_months": 36,
        "currency_options": ["USD", "EUR", "TRY"],
        "step_1_advisories": [
            "Use clear, professional donor proposal language.",
        ],
        "budget_categories": [],
        "indicator_format": "SMART: Specific, Measurable, Achievable, Relevant, Time-bound.",
        "special_requirements": [],
        "section_rules": {
            "step1_executive_intent": {
                "min_characters": 50,
                "max_characters": 500,
                "mandatory_tokens": [],
                "rationale": "Generic donors have minimal pre-screening constraints.",
            },
            "step2_humanitarian_context": {
                "max_characters": 4000,
                "mandatory_tokens": [],
                "rationale": "No donor-specific keyword enforcement for generic proposals.",
            },
            "step2_needs_assessment": {
                "max_characters": 4000,
                "mandatory_tokens": [],
                "rationale": "No donor-specific keyword enforcement for generic proposals.",
            },
            "step2_strategic_justification": {
                "max_characters": 4000,
                "mandatory_tokens": [],
                "rationale": "No donor-specific keyword enforcement for generic proposals.",
            },
        },
        "beneficiary_rules": {
            "disaggregation_required": False,
            "min_vulnerable_quota_percent": 0.0,
            "rationale": "Beneficiary disaggregation is optional for generic donors.",
        },
        "logframe_rules": {
            "max_outcomes": 5,
            "mandatory_levels": ["impact", "outcome", "output", "activity"],
            "rationale": "Generic proposals allow up to 5 outcomes.",
        },
        "financial_rules": {
            "max_overhead_category5_percent": 10.0,
            "psea_mandatory_signoff": True,
            "sphere_standards_required": False,
            "rationale": "Generic donors cap indirect costs at 10%. Sphere standards recommended but not mandatory.",
        },
        "prompt_directive": "Apply standard SMART proposal writing guidelines without rigid donor keyword enforcement. Write in standard donor proposal format with clear sections and SMART indicators.",
    },
}

# Backward-compat: global allowed currencies (union of all donor currency options)
ALLOWED_CURRENCIES = set()
for _d in DONOR_PROFILES.values():
    ALLOWED_CURRENCIES.update(_d.get("currency_options", []))


# ── Manifest helpers ────────────────────────────────────────────────────────


def _donor_profile(setup: dict[str, Any]) -> dict[str, Any]:
    """Return the donor profile dict for a setup, or the generic fallback."""
    return DONOR_PROFILES.get(setup.get("donor", ""), DONOR_PROFILES["generic"])


def _section_rule(donor_profile: dict, section_key: str) -> dict[str, Any]:
    """Return the section rule dict for a step, with safe defaults."""
    rules = donor_profile.get("section_rules", {})
    raw = rules.get(section_key, {})
    return {
        "min_characters": raw.get("min_characters", DEFAULT_INTENT_MIN),
        "max_characters": raw.get("max_characters", DEFAULT_MAX_CHARS),
        "mandatory_tokens": raw.get("mandatory_tokens", []),
        "rationale": raw.get("rationale", ""),
    }


def donor_profiles() -> list[dict[str, Any]]:
    """Return public donor metadata without exposing implementation details."""
    return list(DONOR_PROFILES.values())


# ── Step 1: Setup ───────────────────────────────────────────────────────────


def normalize_setup(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize untrusted request input into the persisted Step 1 shape."""
    sectors = payload.get("sectors", [])
    if isinstance(sectors, str):
        sectors = [item.strip() for item in sectors.split(",") if item.strip()]
    if not isinstance(sectors, list):
        sectors = []

    budget_amount = payload.get("budget_amount")
    try:
        budget_amount = float(budget_amount) if budget_amount not in (None, "") else None
    except (TypeError, ValueError):
        budget_amount = None

    return {
        "project_title": str(payload.get("project_title", "")).strip(),
        "country": str(payload.get("country", "")).strip(),
        "region": str(payload.get("region", "")).strip(),
        "donor": str(payload.get("donor", "")).strip().lower(),
        "budget_amount": budget_amount,
        "budget_currency": str(payload.get("budget_currency", "USD")).strip().upper(),
        "executive_intent": str(payload.get("executive_intent", "")).strip(),
        "sectors": [str(item).strip() for item in sectors if str(item).strip()][:10],
    }


def validate_setup(setup: dict[str, Any]) -> dict[str, Any]:
    """Evaluate deterministic Step 1 rules and return a stable API contract."""
    violations: list[dict[str, str]] = []
    warnings: list[str] = []

    title = setup["project_title"]
    if not 10 <= len(title) <= 150:
        violations.append({"field": "project_title", "message": "Project title must be 10–150 characters."})
    if not setup["country"]:
        violations.append({"field": "country", "message": "Target country is required."})
    if setup["donor"] not in DONOR_PROFILES:
        violations.append({"field": "donor", "message": "Choose a supported primary donor."})
    if setup["budget_amount"] is None or setup["budget_amount"] <= 0:
        violations.append({"field": "budget_amount", "message": "Estimated budget must be a positive number."})

    # Donor-specific currency options (manifest-driven)
    profile = _donor_profile(setup)
    currency_options = profile.get("currency_options", list(ALLOWED_CURRENCIES))
    if setup["budget_currency"] not in currency_options:
        violations.append(
            {"field": "budget_currency", "message": f"Budget currency must be one of: {', '.join(currency_options)}."}
        )

    # Donor-specific executive intent limits (manifest-driven)
    intent_rule = _section_rule(profile, "step1_executive_intent")
    intent = setup["executive_intent"]
    min_len = intent_rule["min_characters"]
    max_len = intent_rule["max_characters"]
    if not min_len <= len(intent) <= max_len:
        violations.append(
            {"field": "executive_intent", "message": f"Executive intent must be {min_len}–{max_len} characters."}
        )

    # Donor-specific mandatory tokens (manifest-driven)
    intent_lower = intent.lower()
    missing_tokens = [t for t in intent_rule["mandatory_tokens"] if t not in intent_lower]
    if missing_tokens:
        violations.append(
            {
                "field": "executive_intent",
                "message": f"Executive intent must include these concepts: {', '.join(missing_tokens)}.",
            }
        )

    if profile:
        warnings.extend(profile["step_1_advisories"])
    if not setup["region"]:
        warnings.append("Add a region when the intervention is not country-wide.")
    if not setup["sectors"]:
        warnings.append("Add at least one sector to make later technical design more precise.")

    return {
        "is_valid": not violations,
        "violations": violations,
        "warnings": warnings,
        "rule_version": "-step-1-2026-08",
    }


# ── Step 2: Context & Needs ──────────────────────────────────────────────────


def normalize_step2(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the editable Step 2 draft without changing Step 1 data."""
    beneficiaries = payload.get("beneficiaries") or {}
    if not isinstance(beneficiaries, dict):
        beneficiaries = {}
    matrix: dict[str, dict[str, int]] = {}
    for category in BENEFICIARY_CATEGORIES:
        source = beneficiaries.get(category) if isinstance(beneficiaries.get(category), dict) else {}
        matrix[category] = {}
        for demographic in BENEFICIARY_DEMOGRAPHICS:
            try:
                value = int(source.get(demographic, 0))
            except (TypeError, ValueError):
                value = 0
            matrix[category][demographic] = max(0, value)
    return {field: str(payload.get(field, "")).strip() for field in STEP2_NARRATIVE_FIELDS} | {"beneficiaries": matrix}


def validate_step2(step2: dict[str, Any], setup: dict[str, Any]) -> dict[str, Any]:
    """Audit Step 2 deterministically; the blind verifier augments this result.

    All donor-specific constraints are read from the DONOR_PROFILES manifest —
    no hardcoded if-else per donor.
    """
    violations: list[dict[str, str]] = []
    warnings: list[str] = []
    metrics = {}

    profile = _donor_profile(setup)
    donor_label = profile["label"]

    # Section character limits + mandatory tokens (manifest-driven)
    field_to_section_key = {
        "humanitarian_context": "step2_humanitarian_context",
        "needs_assessment": "step2_needs_assessment",
        "strategic_justification": "step2_strategic_justification",
    }

    for field in STEP2_NARRATIVE_FIELDS:
        count = len(step2.get(field, ""))
        rule = _section_rule(profile, field_to_section_key[field])
        max_chars = rule["max_characters"]
        metrics[field] = {"char_count": count, "max_allowed": max_chars}
        if count > max_chars:
            violations.append({"field": field, "message": f"This narrative cannot exceed {max_chars:,} characters."})
        if not count:
            violations.append({"field": field, "message": "This narrative is required."})
        # Mandatory token check (manifest-driven)
        text_lower = step2.get(field, "").lower()
        missing = [t for t in rule["mandatory_tokens"] if t not in text_lower]
        if missing:
            # A literal-keyword gate can reject accurate country context (for
            # example, a crisis that is not conflict-driven). The blind verifier
            # still reviews donor alignment, while this rule remains visible as
            # actionable drafting guidance rather than an un-lockable block.
            warnings.append(
                f"{donor_label} guidance for {field}: consider addressing {', '.join(missing)} where relevant to the call and country context."
            )

    # Beneficiary rules (manifest-driven)
    matrix = step2["beneficiaries"]
    totals = {category: sum(matrix[category].values()) for category in BENEFICIARY_CATEGORIES}
    total = sum(totals.values())
    ben_rules = profile.get("beneficiary_rules", {})

    # Disaggregation requirement
    if ben_rules.get("disaggregation_required", True):
        if total <= 0:
            violations.append({"field": "beneficiaries", "message": "Enter at least one target beneficiary."})
        # All demographics must be filled (at least 0 is ok, but matrix must exist)
        for category in BENEFICIARY_CATEGORIES:
            if not isinstance(matrix.get(category), dict):
                violations.append(
                    {
                        "field": "beneficiaries",
                        "message": f"{donor_label} requires a fully disaggregated beneficiary matrix.",
                    }
                )
    else:
        # Generic: beneficiaries optional
        if total <= 0:
            warnings.append("Consider adding target beneficiary numbers if available.")

    # Vulnerable quota (manifest-driven)
    vulnerable = totals["idps"] + totals["refugees_returnees"]
    vulnerable_percentage = round((vulnerable / total * 100), 1) if total else 0.0
    quota = ben_rules.get("min_vulnerable_quota_percent", 0.0)
    if quota > 0 and total > 0 and vulnerable_percentage < quota:
        violations.append(
            {
                "field": "beneficiaries",
                "message": f"{donor_label} requires at least {quota:.0f}% IDP or refugee/returnee beneficiaries.",
            }
        )

    all_text = " ".join(step2.get(field, "").lower() for field in STEP2_NARRATIVE_FIELDS)

    # Generic GBV/trafficking warnings (applies to all donors)
    if "gbv" not in all_text and "gender-based violence" not in all_text:
        warnings.append("Consider describing GBV risks and available referral pathways.")
    if "traffick" not in all_text:
        warnings.append("Consider whether human trafficking risks are relevant in the target area.")

    return {
        "step_id": 2,
        "is_valid": not violations,
        "violations": violations,
        "warnings": warnings,
        "sections_metrics": metrics,
        "beneficiary_summary": {
            "total_beneficiaries": total,
            "vulnerable_percentage": vulnerable_percentage,
            "meets_quota": quota == 0 or vulnerable_percentage >= quota,
        },
        "rule_version": "-step-2-2026-08",
    }


# ── Step 3: Technical Approach & Logframe ────────────────────────────────────


def normalize_step3(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the technical approach, logframe and activity schedule."""
    rows = payload.get("logframe") if isinstance(payload.get("logframe"), list) else []
    logframe = []
    for row in rows[:30]:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level", "")).lower()
        indicators = row.get("indicators") if isinstance(row.get("indicators"), list) else []
        clean_indicators = []
        for indicator in indicators[:10]:
            if not isinstance(indicator, dict):
                continue
            clean_indicators.append(
                {
                    key: str(indicator.get(key, "")).strip()
                    for key in (
                        "indicator_title",
                        "indicator_type",
                        "baseline_value",
                        "target_value",
                        "unit_of_measure",
                        "disaggregation",
                        "data_source_and_frequency",
                        "itt_reference",
                        "pirs_reference",
                    )
                }
            )
        logframe.append(
            {
                "id": str(row.get("id", "")).strip()[:80],
                "level": level,
                "parent_id": str(row.get("parent_id", "")).strip()[:80],
                "intervention_logic": str(row.get("intervention_logic", "")).strip(),
                "means_of_verification": str(row.get("means_of_verification", "")).strip(),
                "assumptions": str(row.get("assumptions", "")).strip(),
                "indicators": clean_indicators,
            }
        )
    gantt = payload.get("gantt") if isinstance(payload.get("gantt"), list) else []
    schedule = []
    for item in gantt[:30]:
        if not isinstance(item, dict):
            continue
        months = item.get("months") if isinstance(item.get("months"), list) else []
        schedule.append(
            {
                "activity_id": str(item.get("activity_id", ""))[:80],
                "months": sorted({int(month) for month in months if str(month).isdigit() and 1 <= int(month) <= 24}),
            }
        )
    hypotheses = payload.get("hypotheses", [])
    if isinstance(hypotheses, str):
        hypotheses = [line.strip(" -•\t") for line in hypotheses.splitlines() if line.strip()]
    return {
        "logframe": logframe,
        "toc_narrative": str(payload.get("toc_narrative", "")).strip()[:4000],
        "hypotheses": [str(item).strip() for item in hypotheses if str(item).strip()][:20],
        "gantt": schedule,
        "grant_months": min(24, max(12, int(payload.get("grant_months", 12) or 12))),
    }


def validate_step3(step3: dict[str, Any], setup: dict[str, Any]) -> dict[str, Any]:
    """Validate logframe vertical/horizontal logic before the blind verifier runs.

    Donor-specific constraints (max_outcomes, HRP alignment, quarterly milestones,
    ITT/PIRS requirements) are read from the manifest.
    """
    violations: list[dict[str, str]] = []
    warnings: list[str] = []

    profile = _donor_profile(setup)
    donor_label = profile["label"]
    lf_rules = profile.get("logframe_rules", {})
    max_outcomes = lf_rules.get("max_outcomes", 3)

    rows = step3["logframe"]
    levels = {level: [row for row in rows if row["level"] == level] for level in LOGFRAME_LEVELS}
    parent_level = {"outcome": "impact", "output": "outcome", "activity": "output"}
    ids_by_level = {level: {row["id"] for row in level_rows if row["id"]} for level, level_rows in levels.items()}
    for level in LOGFRAME_LEVELS:
        if not levels[level]:
            violations.append(
                {"field": "logframe", "message": f"Add at least one {level} row to complete the four-tier logframe."}
            )
    if len(levels["outcome"]) > max_outcomes:
        violations.append(
            {"field": "logframe", "message": f"Use no more than {max_outcomes} outcomes for {donor_label}."}
        )
    if not step3["toc_narrative"]:
        violations.append({"field": "toc_narrative", "message": "Theory of Change narrative is required."})
    if len(step3["toc_narrative"]) > 4000:
        violations.append(
            {"field": "toc_narrative", "message": "Theory of Change narrative cannot exceed 4,000 characters."}
        )

    smart_total = smart_valid = 0
    activity_ids = {row["id"] for row in levels["activity"] if row["id"]}
    schedule_ids = {item["activity_id"] for item in step3["gantt"] if item["months"]}

    itt_pirs_required = lf_rules.get("custom_indicator_itt_pirs_required", False)

    for row in rows:
        expected_parent_level = parent_level.get(row["level"])
        if row["level"] == "impact" and row["parent_id"]:
            violations.append(
                {
                    "field": "logframe_relationship",
                    "message": "Impact rows are the top of the result chain and cannot have a parent.",
                }
            )
        elif expected_parent_level and row["parent_id"] not in ids_by_level[expected_parent_level]:
            violations.append(
                {
                    "field": "logframe_relationship",
                    "message": f"Link each {row['level']} to one {expected_parent_level} so the result chain remains traceable.",
                }
            )
        if not row["intervention_logic"] or not row["means_of_verification"] or not row["assumptions"]:
            violations.append(
                {
                    "field": "logframe",
                    "message": f"Complete intervention logic, means of verification and assumptions for each {row['level']} row.",
                }
            )
        if row["level"] in ("outcome", "output"):
            if not row["indicators"]:
                violations.append(
                    {"field": "indicators", "message": f"Add at least one SMART indicator to every {row['level']}."}
                )
            for indicator in row["indicators"]:
                smart_total += 1
                required = (
                    "indicator_title",
                    "baseline_value",
                    "target_value",
                    "unit_of_measure",
                    "disaggregation",
                    "data_source_and_frequency",
                )
                complete = all(indicator[key] for key in required)
                if complete:
                    smart_valid += 1
                else:
                    violations.append(
                        {
                            "field": "indicators",
                            "message": "Every outcome/output indicator needs title, baseline, target, unit, disaggregation and a data source/frequency.",
                        }
                    )
                if (
                    itt_pirs_required
                    and indicator["indicator_type"].lower() == "custom"
                    and (not indicator["itt_reference"] or not indicator["pirs_reference"])
                ):
                    violations.append(
                        {
                            "field": "indicators",
                            "message": f"{donor_label} custom indicators require ITT and PIRS references.",
                        }
                    )

    # Gantt rules (manifest-driven)
    if activity_ids - schedule_ids:
        violations.append(
            {"field": "gantt", "message": "Map every logframe activity to at least one implementation month."}
        )
    if lf_rules.get("quarterly_activity_milestones_required", False) and any(
        not item["months"] for item in step3["gantt"]
    ):
        violations.append(
            {"field": "gantt", "message": f"{donor_label} activities require concrete quarterly milestones."}
        )

    # HRP alignment (manifest-driven)
    if lf_rules.get("require_hrp_alignment", False) and not levels.get("impact"):
        violations.append(
            {
                "field": "logframe",
                "message": f"{donor_label} requires the standard impact-to-activity hierarchy aligned with the HRP.",
            }
        )

    if not step3["hypotheses"]:
        warnings.append("Add key hypotheses and preconditions to make causal risks explicit.")

    return {
        "step_id": 3,
        "is_valid": not violations,
        "violations": violations,
        "warnings": warnings,
        "logframe_metrics": {
            "outcomes_count": len(levels["outcome"]),
            "outputs_count": len(levels["output"]),
            "activities_count": len(levels["activity"]),
            "indicators_smart_rate": round(smart_valid / smart_total * 100, 1) if smart_total else 0.0,
        },
        "rule_version": "-step-3-2026-08",
    }


# ── Step 4: Financials & Commitments ─────────────────────────────────────────


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def normalize_step4(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("budget_items") if isinstance(payload.get("budget_items"), list) else []
    budget_items = [
        {
            "item_code": str(x.get("item_code", ""))[:20],
            "category": int(_number(x.get("category"))),
            "description": str(x.get("description", "")).strip(),
            "unit_type": str(x.get("unit_type", "")).strip(),
            "quantity": _number(x.get("quantity")),
            "unit_cost": _number(x.get("unit_cost")),
            "duration_frequency": _number(x.get("duration_frequency")),
            "donor_grant_share": _number(x.get("donor_grant_share")),
            "co_financing_share": _number(x.get("co_financing_share")),
        }
        for x in items[:100]
        if isinstance(x, dict)
    ]
    risks = payload.get("risks") if isinstance(payload.get("risks"), list) else []
    risk_rows = [
        {
            "category": str(x.get("category", "")).strip(),
            "risk_description": str(x.get("risk_description", "")).strip(),
            "likelihood": min(5, max(1, int(_number(x.get("likelihood")) or 1))),
            "impact": min(5, max(1, int(_number(x.get("impact")) or 1))),
            "mitigation_strategy": str(x.get("mitigation_strategy", "")).strip(),
        }
        for x in risks[:30]
        if isinstance(x, dict)
    ]
    return {
        "budget_items": budget_items,
        "risks": risk_rows,
        "psea_signoff": bool(payload.get("psea_signoff")),
        "sphere_standards_narrative": str(payload.get("sphere_standards_narrative", "")).strip()[:2000],
    }


def validate_step4(step4: dict[str, Any], setup: dict[str, Any], step3: dict[str, Any]) -> dict[str, Any]:
    """Validate budget, risks, and compliance commitments.

    Donor-specific overhead ceilings, capitalization thresholds, and Sphere
    requirements are read from the financial_rules manifest.
    """
    violations, warnings = [], []

    profile = _donor_profile(setup)
    donor_label = profile["label"]
    fin_rules = profile.get("financial_rules", {})

    items = step4["budget_items"]
    if not items:
        violations.append({"field": "budget_items", "message": "Add at least one itemized budget line."})
    totals = {category: 0.0 for category in range(1, 6)}
    cofinancing = 0.0
    cap_threshold = fin_rules.get("equipment_capitalization_threshold_usd")

    for item in items:
        total = item["quantity"] * item["unit_cost"] * item["duration_frequency"]
        item["total_cost"] = round(total, 2)
        if item["category"] not in totals or not item["description"] or not item["unit_type"] or not total:
            violations.append(
                {
                    "field": "budget_items",
                    "message": "Each budget line needs a valid category, description, unit and positive calculated total.",
                }
            )
        else:
            totals[item["category"]] += total
        cofinancing += item["co_financing_share"]
        if cap_threshold and item["unit_cost"] >= cap_threshold:
            warnings.append(
                f"{item['item_code'] or item['description']}: inventory/property tracking is required for this ${cap_threshold:,.0f}+ item."
            )

    total_budget = sum(totals.values())
    direct = sum(totals[c] for c in range(1, 5))
    overhead = totals[5]
    overhead_pct = round(overhead / direct * 100, 2) if direct else 0.0

    # Overhead ceiling (manifest-driven)
    overhead_ceiling = fin_rules.get("max_overhead_category5_percent", 10.0)
    if overhead_pct > overhead_ceiling:
        violations.append(
            {
                "field": "budget_items",
                "message": f"{donor_label} indirect overhead cannot exceed {overhead_ceiling:.0f}% of direct eligible costs.",
            }
        )

    # PSEA (manifest-driven)
    if fin_rules.get("psea_mandatory_signoff", True) and not step4["psea_signoff"]:
        violations.append(
            {"field": "psea_signoff", "message": "PSEA sign-off to the six IASC core principles is mandatory."}
        )

    # Sphere standards (manifest-driven — Generic: False)
    if fin_rules.get("sphere_standards_required", True) and not step4["sphere_standards_narrative"]:
        violations.append({"field": "sphere_standards_narrative", "message": "Describe Sphere standards adherence."})

    # Risks
    if not step4["risks"]:
        violations.append({"field": "risks", "message": "Add at least one risk management entry."})
    high = sum(1 for risk in step4["risks"] if risk["likelihood"] * risk["impact"] >= 15)
    if any(not x["risk_description"] or not x["mitigation_strategy"] or not x["category"] for x in step4["risks"]):
        violations.append(
            {"field": "risks", "message": "Each risk needs category, description and actionable mitigation."}
        )

    # Localization subgrant recommendation (warning only)
    localization_reco = fin_rules.get("localization_min_subgrant_recommendation_percent")
    if localization_reco and total_budget > 0:
        localization_pct = round(totals[4] / total_budget * 100, 2)
        if localization_pct < localization_reco:
            warnings.append(
                f"{donor_label} recommends at least {localization_reco:.0f}% localization/subgrant budget. Current: {localization_pct:.1f}%."
            )

    return {
        "step_id": 4,
        "is_valid": not violations,
        "violations": violations,
        "warnings": warnings,
        "financial_summary": {
            "total_budget": round(total_budget, 2),
            "direct_costs": round(direct, 2),
            "indirect_overhead": round(overhead, 2),
            "indirect_overhead_percentage": overhead_pct,
            "co_financing_percentage": round(cofinancing / total_budget * 100, 2) if total_budget else 0.0,
            "localization_subgrant_percentage": round(totals[4] / total_budget * 100, 2) if total_budget else 0.0,
        },
        "risk_summary": {"total_risks_identified": len(step4["risks"]), "high_severity_risks": high},
        "rule_version": "-step-4-2026-08",
    }
