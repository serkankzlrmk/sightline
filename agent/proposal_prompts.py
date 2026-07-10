"""
proposal_prompts.py — Step-specific system prompts for the proposal wizard.

Each prompt instructs the agent on:
- What section to write
- Which tools to use (if any)
- What structure to follow
- What output format to return (JSON or markdown)
"""

SECTION_PROMPTS = {
    "cover": {
        "system": """You are writing the Cover Page of a humanitarian donor proposal.

Use the provided country, event, and donor information to create a professional cover page.

Return a JSON object with these fields:
{
  "project_title": "Full official title",
  "country": "Country name",
  "crisis_event": "Brief event description",
  "donor": "Donor name",
  "duration_months": "e.g. 12",
  "budget_summary": "e.g. $500,000",
  "implementing_partner": "Partner org name or TBD",
  "target_beneficiaries": "e.g. 10,000 IDPs and host community members",
  "sectors": "e.g. WASH, Protection, Shelter",
  "summary": "2-3 sentence project summary"
}

Return ONLY the JSON object.""",
        "tools": [],
        "output_format": "json",
    },

    "background": {
        "system": """You are writing the Context & Background section of a humanitarian donor proposal.

Call AT MOST 2 tools to gather data. Do not call more than 2 tools.
- search_knowledge_base: Search ReliefWeb reports for context (call this FIRST)
- search_disasters OR get_latest_headlines: Get recent events (call ONE of these)

Write a comprehensive background section covering:
1. Crisis overview and timeline
2. Affected population (displacement numbers, casualties if available)
3. Humanitarian access constraints
4. Current response situation
5. Key drivers and underlying vulnerabilities

Write in clear, professional markdown with ## headers.
Return JSON: {"content": "# markdown content here...", "sources": [{"title": "...", "url": "..."}]}
Return ONLY the JSON. Do not wrap in markdown code blocks.""",
        "tools": ["search_knowledge_base", "search_disasters"],
        "output_format": "json",
    },

    "needs_assessment": {
        "system": """You are writing the Needs Assessment section of a humanitarian donor proposal.

Call AT MOST 2 tools to gather data. Do not call more than 2 tools — synthesize from what you have.
- search_knowledge_base: Search for needs assessment reports (call this FIRST)
- hdx_get_refugees OR hdx_get_idps: Get displacement data (call ONE of these, not both)

Write a structured needs assessment covering:
1. **Affected Population Analysis** — Demographics, displacement patterns, vulnerability groups
2. **Sectoral Needs** — Break down by theme (WASH, Health, Protection, Shelter, Food Security, Education)
3. **Gap Analysis** — What is currently covered vs. gaps in response
4. **Vulnerability Assessment** — Specific vulnerable groups and their needs
5. **Priority Needs** — Ranked list of most urgent needs

Include specific numbers where available. Write in professional markdown.
Return JSON: {"content": "# markdown content here...", "sources": [{"title": "...", "url": "..."}]}
Return ONLY the JSON. Do not wrap in markdown code blocks.""",
        "tools": ["search_knowledge_base", "hdx_get_refugees", "worldbank_get_indicator"],
        "output_format": "json",
    },

    "toc": {
        "system": """You are creating the Theory of Change (ToC) for a humanitarian donor proposal.

Based on the country context, needs assessment, and previous sections, create a logical ToC chain.

The ToC must follow the standard chain: Activity → Output → Outcome → Impact.

Return a JSON array with exactly 4 objects (or more if the project is multi-sector):
[
  {"level": "impact", "text": "Long-term ultimate change/goal"},
  {"level": "outcome", "text": "Specific change in behavior/status of target population"},
  {"level": "output", "text": "Direct tangible product/deliverable of activities"},
  {"level": "activity", "text": "Key actions to produce outputs"}
]

For multi-sector proposals, you may include multiple outcomes/outputs.
Ensure each level logically leads to the next.
Return ONLY the JSON array.""",
        "tools": ["search_knowledge_base"],
        "output_format": "json",
    },

    "logframe": {
        "system": """You are creating the Logical Framework Matrix for a humanitarian donor proposal.

The logframe must be derived from the Theory of Change. Create a structured matrix with:

Return a JSON object:
{
  "goal": "G1. [Overall goal statement from ToC impact level]",
  "goal_indicator": "Indicator: [SMART indicator]. Source: [data source]. Frequency: [timing]",
  "goal_assumptions": "Key assumptions for goal achievement",

  "outcomes": "OC1. [Outcome statement from ToC]. Target: [number]",
  "outcomes_indicator": "Indicator: [SMART indicator]. Baseline: [value]. Target: [value]. Source: [source]",
  "outcomes_assumptions": "Assumptions for outcome achievement",

  "outputs": "O1. [Output statement from ToC]. Target: [number]",
  "outputs_indicator": "Indicator: [SMART indicator]. Baseline: [value]. Target: [value]. Source: [source]",
  "outputs_sources": "Data sources for verification",

  "activities": "A1. [Activity 1]. A2. [Activity 2]. A3. [Activity 3]",
  "activities_inputs": "Key inputs: staff, materials, equipment",
  "activities_budget": "Estimated budget per activity",
  "activities_preconditions": "Preconditions for starting activities"
}

Ensure indicators are SMART (Specific, Measurable, Achievable, Relevant, Time-bound).
Return ONLY the JSON object.""",
        "tools": [],
        "output_format": "json",
    },

    "methodology": {
        "system": """You are writing the Methodology section of a humanitarian donor proposal.

Based on the logframe and ToC, describe the operational approach.

Cover:
1. **Overall Approach** — Guiding principles (do-no-harm, conflict-sensitive, participatory)
2. **Targeting Strategy** — How beneficiaries will be identified and selected
3. **Implementation Modalities** — Direct implementation, partners, cash-based, in-kind
4. **Key Activities** — Detailed description of main activities per output
5. **Timeline** — High-level timeline/Gantt structure (by quarter or month)
6. **Cross-cutting Issues** — Gender, protection mainstreaming, accountability (AAP/PHA)
7. **Beneficiary Participation** — How communities are involved in design and M&E

Write in professional markdown with ## headers.
Return JSON: {"content": "# markdown content here...", "sources": []}
Return ONLY the JSON.""",
        "tools": [],
        "output_format": "json",
    },

    "budget": {
        "system": """You are creating the Budget Summary for a humanitarian donor proposal.

Create a structured budget summary by sector/category. Use World Bank indicators if needed for unit cost estimation.

Return a JSON object:
{
  "total": "Total estimated amount (e.g. $450,000)",
  "currency": "USD",
  "duration_months": 12,
  "lines": [
    {"category": "Staff & Personnel", "description": "Project coordinator, field officers, M&E officer", "amount": "$120,000", "percentage": "27%"},
    {"category": "Activities & Supplies", "description": "Relief kits, WASH supplies, training materials", "amount": "$200,000", "percentage": "44%"},
    {"category": "Logistics & Transport", "description": "Warehousing, distribution transport, fuel", "amount": "$50,000", "percentage": "11%"},
    {"category": "Monitoring & Evaluation", "description": "Baseline, endline, data collection, third-party monitoring", "amount": "$30,000", "percentage": "7%"},
    {"category": "Administration & Overhead", "description": "Office, communications, audit, compliance", "amount": "$50,000", "percentage": "11%"}
  ]
}

Adjust amounts and categories based on the project context.
Return ONLY the JSON object.""",
        "tools": ["worldbank_get_indicator"],
        "output_format": "json",
    },

    "mne_framework": {
        "system": """You are creating the Monitoring & Evaluation Framework for a humanitarian donor proposal.

Based on the logframe indicators, create a comprehensive M&E framework.

Return a JSON object:
{
  "framework_approach": "Brief description of M&E approach (e.g. results-based, participatory)",
  "data_collection_methods": ["Survey", "FFF (Focus group discussions)", "Key informant interviews", "Post-distribution monitoring", "Remote monitoring"],
  "frequency": "Monitoring frequency (e.g. monthly activity monitoring, quarterly outcome monitoring)",
  "indicators": [
    {
      "name": "Indicator name from logframe",
      "type": "output/outcome/impact",
      "baseline": "Baseline value",
      "target": "Target value",
      "source": "Data source (e.g. PDM, survey, KII)",
      "frequency": "Collection frequency",
      "responsible": "Who collects (M&E officer, field team)"
    }
  ],
  "accountability_mechanism": "Description of AAP/feedback mechanism",
  "learning_agenda": "Key learning questions for the project"
}

Include at least 5-8 indicators covering output, outcome, and impact levels.
Return ONLY the JSON object.""",
        "tools": [],
        "output_format": "json",
    },

    "risk_matrix": {
        "system": """You are creating the Risk Matrix for a humanitarian donor proposal.

Identify key project risks and mitigation measures.

Return a JSON array of risk objects:
[
  {
    "risk": "Description of the risk",
    "category": "Operational/Security/Financial/Political/Programmatic/External",
    "probability": "Low/Medium/High",
    "impact": "Low/Medium/High",
    "mitigation": "Specific mitigation measures",
    "contingency": "Contingency plan if risk materializes"
  }
]

Include at least 6-8 risks covering different categories.
Prioritize risks by probability × impact.
Return ONLY the JSON array.""",
        "tools": [],
        "output_format": "json",
    },

    "sustainability": {
        "system": """You are writing the Sustainability & Exit Strategy section of a humanitarian donor proposal.

Cover:
1. **Sustainability Approach** — How benefits will be sustained after project ends
2. **Capacity Building** — Local capacity strengthening activities
3. **Community Ownership** — How communities will own and maintain results
4. **Institutional Handover** — Handover to local authorities/institutions
5. **Financial Sustainability** — Resource mobilisation beyond project
6. **Exit Strategy** — Phased exit plan with transition milestones
7. **Lessons Learned** — How learning will be captured and shared

Write in professional markdown with ## headers.
Return JSON: {"content": "# markdown content here...", "sources": []}
Return ONLY the JSON.""",
        "tools": [],
        "output_format": "json",
    },

    "coordination": {
        "system": """You are writing the Coordination section of a humanitarian donor proposal.

Use available tools to identify coordination mechanisms and partners.
- search_sources: Find humanitarian coordination bodies and partners active in the country

Cover:
1. **Cluster Coordination** — Which clusters the project contributes to (e.g. Protection, WASH, Shelter, CCCM)
2. **Implementing Partners** — Description of partners and their roles
3. **Inter-agency Coordination** — Participation in OCHA, HCT, cluster meetings
4. **Government Engagement** — Relationship with local/national authorities
5. **Referral Pathways** — Inter-agency referral mechanisms

Write in professional markdown with ## headers.
Return JSON: {"content": "# markdown content here...", "sources": [{"title": "...", "url": "..."}]}
Return ONLY the JSON.""",
        "tools": ["search_sources"],
        "output_format": "json",
    },

    "final_review": {
        "system": """You are compiling the Final Narrative of a humanitarian donor proposal.

Review all previous sections and create a cohesive, full proposal narrative that:
1. Integrates all sections into a single flowing document
2. Ensures consistency across sections (ToC → logframe → methodology → M&E)
3. Adds transition paragraphs between sections
4. Highlights the project's value proposition and alignment with donor priorities
5. Includes an executive summary at the top

Write in professional markdown. This should read as a complete, submission-ready proposal.
Return JSON: {"content": "# full markdown narrative here...", "sources": []}
Return ONLY the JSON.""",
        "tools": [],
        "output_format": "json",
    },
}


SECTION_ORDER = [
    "cover", "background", "needs_assessment", "toc", "logframe",
    "methodology", "budget", "mne_framework", "risk_matrix",
    "sustainability", "coordination", "final_review",
]


def get_section_prompt(step: str) -> dict:
    """Get the prompt configuration for a specific section."""
    return SECTION_PROMPTS.get(step, {"system": "", "tools": [], "output_format": "text"})


def build_user_context(step: str, proposal_row: dict) -> str:
    """Build the user message with proposal context for the agent."""
    parts = []
    parts.append(f"Country: {proposal_row.get('country', '')}")
    parts.append(f"Event/Crisis: {proposal_row.get('event', '')}")
    parts.append(f"Donor: {proposal_row.get('donor', '')}")

    try:
        from agent.donor_templates import get_template_directive
        donor_directive = get_template_directive(proposal_row.get('donor', ''))
        if donor_directive:
            parts.append(f"\n--- DONOR FORMAT REQUIREMENTS ---\n{donor_directive}")
    except ImportError:
        pass

    try:
        themes = json.loads(proposal_row.get("themes", "[]"))
        if isinstance(themes, str):
            themes = [t.strip() for t in themes.split(",") if t.strip()]
    except Exception:
        themes = [t.strip() for t in str(proposal_row.get("themes", "")).split(",") if t.strip()]
    parts.append(f"Themes/Sectors: {', '.join(themes) if themes else 'General'}")
    parts.append(f"Date Range: {proposal_row.get('date_from', '')} to {proposal_row.get('date_to', '')}")

    section_contexts = {
        "toc": "logframe",
        "logframe": "toc",
        "methodology": "toc",
        "budget": "toc",
        "mne_framework": "logframe",
        "risk_matrix": "methodology",
        "sustainability": "methodology",
        "coordination": "background",
        "final_review": "narrative",
    }

    prev_sections = []
    if step in ("background", "needs_assessment"):
        prev_sections.append("cover")
    elif step in ("toc", "logframe"):
        prev_sections.extend(["background", "needs_assessment"])
    elif step == "methodology":
        prev_sections.extend(["background", "needs_assessment", "toc", "logframe"])
    elif step in ("budget", "mne_framework", "risk_matrix", "sustainability", "coordination"):
        prev_sections.extend(["background", "needs_assessment", "toc", "logframe", "methodology"])
    elif step == "final_review":
        prev_sections = SECTION_ORDER[:-1]

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

    for prev_step in prev_sections:
        field = field_map.get(prev_step, prev_step)
        content = proposal_row.get(field, "")
        if content and content not in ("", "{}", "[]"):
            parts.append(f"\n--- Previous Section: {prev_step} ---\n{content[:3000]}")

    reference_text = proposal_row.get("reference_text", "")
    if reference_text:
        parts.append(f"\n--- REFERENCE DOCUMENT (uploaded by user) ---\n{reference_text[:15000]}")

    return "\n".join(parts)


import json
