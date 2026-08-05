"""
donor_templates.py — Donor-specific proposal format templates.

Each template defines:
- Required sections and their order
- Section heading formats
- Word/character limits per section
- Indicator format requirements
- Budget categories
- Special requirements (e.g. gender marker for ECHO)

Templates are injected into the agent's system prompt during section generation.
"""

DONOR_TEMPLATES = {
    "ECHO": {
        "name": "ECHO Humanitarian Implementation Plan (HIP)",
        "full_name": "European Civil Protection and Humanitarian Aid Operations",
        "sections": [
            {"key": "cover", "label": "Project Identification", "max_words": 500},
            {"key": "background", "label": "Humanitarian Situation", "max_words": 1500},
            {"key": "needs_assessment", "label": "Needs Assessment", "max_words": 1500},
            {"key": "toc", "label": "Logical Framework — Results", "max_words": None},
            {"key": "logframe", "label": "Logical Framework Matrix", "max_words": None},
            {"key": "methodology", "label": "Methodology & Implementation", "max_words": 2000},
            {"key": "budget", "label": "Budget Breakdown", "max_words": None},
            {"key": "mne_framework", "label": "Monitoring & Reporting", "max_words": 1000},
            {"key": "risk_matrix", "label": "Risk Assessment", "max_words": 1000},
            {"key": "sustainability", "label": "Exit Strategy", "max_words": 800},
            {"key": "coordination", "label": "Coordination & Complementarity", "max_words": 800},
            {"key": "final_review", "label": "Full Proposal", "max_words": None},
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
        "prompt_directive": """You are writing for an ECHO HIP (Humanitarian Implementation Plan) proposal.
Follow ECHO format strictly:
- Section headings must match ECHO template
- Budget must use ECHO cost categories (Staff, Travel, Equipment, Transport, etc.)
- Indirect costs must not exceed 7% of total budget
- Include gender marker assessment (0=no gender, 1=gender mainstreamed, 2=gender transformative)
- Reference ECHO HIP thematic priorities for the country
- Indicators must follow ECHO methodology: baseline → target → source → frequency""",
    },
    "USAID": {
        "name": "USAID/BHA Application",
        "full_name": "U.S. Agency for International Development / Bureau for Humanitarian Assistance",
        "sections": [
            {"key": "cover", "label": "Application Summary", "max_words": 500},
            {"key": "background", "label": "Context & Situation Analysis", "max_words": 2000},
            {"key": "needs_assessment", "label": "Needs Assessment & Gap Analysis", "max_words": 2000},
            {"key": "toc", "label": "Results Framework — Objectives", "max_words": None},
            {"key": "logframe", "label": "Logical Framework", "max_words": None},
            {"key": "methodology", "label": "Program Description & Methodology", "max_words": 3000},
            {"key": "budget", "label": "Budget Summary by Objective", "max_words": None},
            {"key": "mne_framework", "label": "Monitoring, Evaluation & Learning", "max_words": 1500},
            {"key": "risk_matrix", "label": "Risk Management Plan", "max_words": 1000},
            {"key": "sustainability", "label": "Sustainability & Transition", "max_words": 1000},
            {"key": "coordination", "label": "Coordination & Partnerships", "max_words": 800},
            {"key": "final_review", "label": "Complete Application", "max_words": None},
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
        "prompt_directive": """You are writing for a USAID/BHA application.
Follow USAID/BHA format strictly:
- Use Results Framework terminology (Objectives, Sub-Objectives, Outputs)
- Budget must use BHA cost categories (Personnel, Fringe, Travel, Equipment, Supplies, Contractual, etc.)
- Indirect costs must be based on NICRA or 10% de minimis
- Include disability inclusion strategy (Washington Group Questions)
- Include gender analysis and safeguarding measures
- MEAL plan must include learning component
- Indicators must include disaggregation by sex, age, and disability where relevant""",
    },
    "OCHA": {
        "name": "OCHA CBPF (Country-Based Pooled Fund)",
        "full_name": "UN OCHA Country-Based Pooled Fund",
        "sections": [
            {"key": "cover", "label": "Project Summary", "max_words": 300},
            {"key": "background", "label": "Context Overview", "max_words": 1000},
            {"key": "needs_assessment", "label": "Needs & Prioritization", "max_words": 1500},
            {"key": "toc", "label": "Project Logic", "max_words": None},
            {"key": "logframe", "label": " Logical Framework", "max_words": None},
            {"key": "methodology", "label": "Implementation Approach", "max_words": 2000},
            {"key": "budget", "label": "Budget Summary", "max_words": None},
            {"key": "mne_framework", "label": "Monitoring Plan", "max_words": 1000},
            {"key": "risk_matrix", "label": "Risk Management", "max_words": 800},
            {"key": "sustainability", "label": "Sustainability", "max_words": 500},
            {"key": "coordination", "label": "Coordination Mechanisms", "max_words": 600},
            {"key": "final_review", "label": "Full Project Document", "max_words": None},
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
            "Must align with current HRP (Humanitarian Response Plan) strategic objectives",
            "Must reference cluster strategic objectives",
            "Programme support costs must not exceed 7%",
            "Must include AAP (Accountability to Affected Populations) measures",
            "Maximum project duration 12 months (exceptional 24 months)",
            "CBPF gender marker code required (0-2)",
        ],
        "prompt_directive": """You are writing for an OCHA CBPF (Country-Based Pooled Fund) proposal.
Follow CBPF format strictly:
- Align project objectives with HRP (Humanitarian Response Plan) strategic objectives
- Reference cluster coordination mechanisms
- Budget: Programme support costs must not exceed 7%
- Include AAP (Accountability to Affected Populations) measures
- Gender marker code required (0-2)
- Maximum 12-month duration
- Indicators must align with cluster HRP indicators""",
    },
    "Generic": {
        "name": "Generic Donor Proposal",
        "full_name": "Standard humanitarian proposal format",
        "sections": [
            {"key": "cover", "label": "Cover Page", "max_words": None},
            {"key": "background", "label": "Context & Background", "max_words": None},
            {"key": "needs_assessment", "label": "Needs Assessment", "max_words": None},
            {"key": "toc", "label": "Theory of Change", "max_words": None},
            {"key": "logframe", "label": "Logical Framework", "max_words": None},
            {"key": "methodology", "label": "Methodology", "max_words": None},
            {"key": "budget", "label": "Budget Summary", "max_words": None},
            {"key": "mne_framework", "label": "Monitoring & Evaluation", "max_words": None},
            {"key": "risk_matrix", "label": "Risk Matrix", "max_words": None},
            {"key": "sustainability", "label": "Sustainability & Exit", "max_words": None},
            {"key": "coordination", "label": "Coordination", "max_words": None},
            {"key": "final_review", "label": "Full Narrative", "max_words": None},
        ],
        "budget_categories": [],
        "indicator_format": "SMART: Specific, Measurable, Achievable, Relevant, Time-bound.",
        "special_requirements": [],
        "prompt_directive": "Write in standard donor proposal format with clear sections and SMART indicators.",
    },
}


def get_template(donor: str) -> dict:
    """Get donor template by name. Falls back to Generic."""
    return DONOR_TEMPLATES.get(donor, DONOR_TEMPLATES["Generic"])


def get_template_directive(donor: str) -> str:
    """Get the donor-specific prompt directive for injection into agent prompts."""
    template = get_template(donor)
    return template.get("prompt_directive", "")


def list_templates() -> list[dict]:
    """List available donor templates for frontend selection."""
    return [
        {"key": k, "name": v["name"], "full_name": v["full_name"]} for k, v in DONOR_TEMPLATES.items() if k != "Generic"
    ]
