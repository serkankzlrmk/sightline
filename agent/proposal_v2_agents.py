"""Guided Proposal V2 — LLM orchestration with generator/verifier separation.

Generator uses LangGraph + tool-calling (ReliefWeb, HDX, Brave search) to enrich
proposal narratives with real humanitarian data.  Verifier remains blind — it
receives only the normalized output and donor rule manifest, never the generator
prompt history or tool results.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.proposal_v2_rules import DONOR_PROFILES
from config import config

logger = logging.getLogger(__name__)

MAX_REFINEMENTS = 3
_RECURSION_LIMIT = 15

# ── Step → tool subset mapping ───────────────────────────────────────────────
# Verifier never gets tools — only the generator.
_STEP_TOOLS: dict[str, list[str]] = {
    "1": ["search_sitreps", "search_knowledge_base", "search_sources"],
    "2": [
        "search_sitreps",
        "search_knowledge_base",
        "search_sources",
        "hdx_get_refugees",
        "hdx_get_funding",
        "brave_web_search",
    ],
    "3": ["search_knowledge_base", "search_sitreps"],
}


def _model(temperature: float, max_tokens: int = 4096):
    return ChatOpenAI(
        model=os.environ.get("PROPOSAL_MODEL", "google/gemini-2.5-flash"),
        base_url=config._LLM_BASE_URL,
        api_key=config._LLM_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=120,
    )


def _json(text: str) -> dict:
    text = str(text or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = text.find("{")
    if start >= 0:
        return json.JSONDecoder().raw_decode(text[start:])[0]
    raise ValueError("No JSON object returned")


def _normalize_indicator_drafts(logframe: list) -> list:
    """Make model indicator output editable and validation-ready.

    Models sometimes return a plain indicator string despite the requested
    object schema. Keep that text as the title and add explicit, reviewable
    draft metadata so the user can analyze and refine it instead of receiving
    an empty indicator array.
    """
    fields = {
        "indicator_type": "standard",
        "baseline_value": "To be established in inception survey",
        "target_value": "To be finalized after baseline",
        "unit_of_measure": "Number or percentage",
        "disaggregation": "Sex, age and disability",
        "data_source_and_frequency": "Project monitoring records / quarterly",
        "itt_reference": "",
        "pirs_reference": "",
    }
    for row in logframe:
        if not isinstance(row, dict):
            continue
        raw = row.get("indicators") if isinstance(row.get("indicators"), list) else []
        normalized = []
        for item in raw[:2]:
            if isinstance(item, str):
                item = {"indicator_title": item}
            if not isinstance(item, dict):
                continue
            indicator = dict(fields)
            indicator.update({key: str(value or "").strip() for key, value in item.items()})
            if indicator["indicator_title"]:
                normalized.append(indicator)
        row["indicators"] = normalized
    return logframe


def _get_tools_for_step(step: str):
    """Resolve the tool subset for a generator step from ReliefAgent's registry."""
    names = _STEP_TOOLS.get(step, [])
    if not names:
        return []
    try:
        from agent.relief_agent import tools_by_name
    except ImportError:
        logger.warning("Could not import tools_by_name from relief_agent")
        return []
    selected = []
    for name in names:
        if name in tools_by_name:
            selected.append(tools_by_name[name])
        else:
            logger.warning(f"Tool '{name}' not found for proposal step {step}")
    return selected


def _run_generator_with_tools(system_prompt: str, user_content: str, step: str, max_tokens: int = 4096) -> tuple[str, list]:
    """Run the generator as a LangGraph agent with tool-calling.

    Returns (response_text, sources).  Falls back to plain invoke if tools
    are unavailable or the agent loop fails.
    """
    tools = _get_tools_for_step(step)
    model = _model(0.2, max_tokens=max_tokens)

    if not tools:
        response = model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ]
        )
        return (response.content if hasattr(response, "content") else str(response), [])

    try:
        model_bound = model.bind_tools(tools)
        from langgraph.graph import START, StateGraph
        from langgraph.graph.message import MessagesState
        from langgraph.prebuilt import ToolNode

        def llm_call(state: MessagesState):
            messages = state["messages"]
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=system_prompt)] + messages
            return {"messages": model_bound.invoke(messages)}

        builder = StateGraph(MessagesState)
        builder.add_node("llm_call", llm_call)
        builder.add_node("tool_node", ToolNode(tools))
        builder.add_edge(START, "llm_call")
        builder.add_conditional_edges(
            "llm_call",
            lambda s: "tool_node" if s["messages"][-1].tool_calls else "__end__",
            ["tool_node", "__end__"],
        )
        builder.add_edge("tool_node", "llm_call")
        agent = builder.compile()

        result = agent.invoke(
            {"messages": [HumanMessage(content=user_content)]},
            config={"recursion_limit": _RECURSION_LIMIT},
        )

        response_text = ""
        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
                if not getattr(msg, "tool_calls", None):
                    response_text = msg.content
                    break

        if not response_text:
            for msg in reversed(result.get("messages", [])):
                if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
                    response_text = msg.content
                    break

        if not response_text:
            tool_results = []
            for msg in result.get("messages", []):
                if (
                    hasattr(msg, "content")
                    and isinstance(msg.content, str)
                    and msg.content
                    and getattr(msg, "name", "")
                ):
                    tool_results.append(f"[{msg.name}]: {msg.content[:500]}")
            if tool_results:
                response_text = "Based on the research:\n\n" + "\n\n".join(tool_results)
            else:
                response_text = ""

        # Strip <think> tags some providers inject
        if response_text:
            response_text = re.sub(r"<think>.*?</think>", "", response_text, flags=re.DOTALL).strip()

        return (response_text, [])

    except Exception as exc:
        logger.warning(f"Tool-enabled generator failed for step {step}: {exc} — falling back to plain invoke")
        response = model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ]
        )
        return (response.content if hasattr(response, "content") else str(response), [])


# ── Step 1 ────────────────────────────────────────────────────────────────────


def summarize_call_document(setup: dict) -> dict:
    """Turn an uploaded grant call into a factual, user-facing briefing.

    This is a reading aid, not a compliance verdict: every item is grounded in
    the uploaded text and explicitly marked as absent when the call is silent.
    """
    call_text = str(setup.get("reference_text", "")).strip()
    if not call_text:
        raise ValueError("No call document is attached.")
    prompt = """You are a grant-call reader helping a proposal writer understand an uploaded call.
Use ONLY the uploaded document. Do not infer, search the web, or invent requirements.
Write concise plain English suitable for an on-screen briefing. If information is absent,
say "Not specified in the uploaded call." Return JSON only with this exact shape:
{"overview":"...","eligible_applicants":["..."],"priority_outcomes":["..."],
"required_deliverables":["..."],"financial_and_timing":["..."],
"evaluation_criteria":["..."],"open_questions":["..."],"important_notes":["..."]}
"""
    parsed = _json(
        _model(0.1, max_tokens=2200)
        .invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(content=call_text[:30000]),
            ]
        )
        .content
    )
    list_keys = (
        "eligible_applicants",
        "priority_outcomes",
        "required_deliverables",
        "financial_and_timing",
        "evaluation_criteria",
        "open_questions",
        "important_notes",
    )
    for key in list_keys:
        if not isinstance(parsed.get(key), list):
            parsed[key] = ["Not specified in the uploaded call."]
    if not isinstance(parsed.get("overview"), str):
        parsed["overview"] = "The uploaded call could not be summarized reliably."
    return parsed


def generate_step_one_draft(setup: dict) -> dict:
    """Create an editable Step 1 draft from the call document and user seeds.

    This is deliberately separate from ``analyze_step_one``: the generator
    helps the user write, while the blind verifier later evaluates the user's
    accepted wording.  The two responsibilities must not be conflated.
    """
    donor = DONOR_PROFILES.get(setup.get("donor"), DONOR_PROFILES["generic"])
    source = {
        "existing_fields": {
            key: setup.get(key, "")
            for key in (
                "project_title",
                "country",
                "region",
                "donor",
                "budget_amount",
                "budget_currency",
                "executive_intent",
                "sectors",
            )
        },
        "call_document": str(setup.get("reference_text", ""))[:16000],
    }
    prompt = f"""{donor.get("prompt_directive", "")}

You are a proposal co-writer. Create a concise, EDITABLE Step 1 project setup.
Use only facts in the supplied call document and existing user inputs. Do not
invent an eligibility rule, budget ceiling, location, or implementing partner.
Keep a user-supplied donor and currency unchanged. If a fact is absent, keep
the existing value or use an empty string. Executive intent must be 100-500
characters and written as donor-ready plain language.

Return JSON only with this exact shape:
{{"project_title":"...","country":"...","region":"...","donor":"...",
"budget_amount":null,"budget_currency":"...","executive_intent":"...",
"sectors":["..."],"draft_notes":["..."]}}"""
    parsed = _json(
        _model(0.25, max_tokens=1800)
        .invoke(
            [
                SystemMessage(content=prompt),
                HumanMessage(content=json.dumps(source, ensure_ascii=False)),
            ]
        )
        .content
    )
    if not isinstance(parsed.get("sectors"), list):
        parsed["sectors"] = setup.get("sectors", [])
    # Never let a creative model silently swap the selected donor/currency.
    parsed["donor"] = setup.get("donor") or parsed.get("donor", "generic")
    parsed["budget_currency"] = setup.get("budget_currency") or parsed.get("budget_currency", "USD")
    return parsed


def generate_step_two_draft(setup: dict) -> dict:
    """Create an editable context draft even when the user has not typed yet."""
    donor = DONOR_PROFILES.get(setup.get("donor"), DONOR_PROFILES["generic"])
    source = {
        "locked_step_1_contract": {
            key: setup.get(key, "")
            for key in (
                "project_title",
                "country",
                "region",
                "donor",
                "budget_amount",
                "budget_currency",
                "executive_intent",
                "sectors",
            )
        },
        "call_document": str(setup.get("reference_text", ""))[:16000],
    }
    prompt = f"""{donor.get("prompt_directive", "")}

You are a proposal co-writer. Draft the three editable Step 2 narratives from
the locked project setup and attached grant call. The user has not written a
first draft yet, so do not wait for one. Use the call document first; when it
does not contain context evidence, you may use the available research tools to
find current reliable humanitarian data. Cite every external factual claim as
[Source: title](URL). Never invent statistics, operational presence, partners,
or eligibility. Keep each narrative under 4,000 characters.

Return JSON only:
{{"humanitarian_context":"...","needs_assessment":"...",
"strategic_justification":"...","draft_notes":["..."],"sources":[{{"title":"...","url":"..."}}]}}"""
    raw, discovered_sources = _run_generator_with_tools(prompt, json.dumps(source, ensure_ascii=False), "2")
    parsed = _json(raw)
    for key in ("humanitarian_context", "needs_assessment", "strategic_justification"):
        if not isinstance(parsed.get(key), str):
            parsed[key] = ""
    if not isinstance(parsed.get("draft_notes"), list):
        parsed["draft_notes"] = []
    if not isinstance(parsed.get("sources"), list):
        parsed["sources"] = discovered_sources
    return parsed


def generate_step_three_draft(setup: dict) -> dict:
    """Create an editable ToC/logframe draft after Context & Needs is locked."""
    donor = DONOR_PROFILES.get(setup.get("donor"), DONOR_PROFILES["generic"])
    source = {
        "locked_setup": {key: setup.get(key, "") for key in ("project_title", "country", "region", "donor", "sectors")},
        "context_and_needs": setup.get("context_data", {}),
        "current_technical_design": setup.get("technical_data", {}),
        "call_document": str(setup.get("reference_text", ""))[:12000],
    }
    prompt = f"""{donor.get('prompt_directive', '')}
Create an editable Step 3 technical design from the locked setup, context and uploaded call.
Return JSON only with this shape:
{{"toc_narrative":"...","hypotheses":["..."],"grant_months":12,
"logframe":[{{"id":"impact-1","level":"impact","parent_id":"","intervention_logic":"...","indicators":[{{"indicator_title":"...","baseline_value":"...","target_value":"...","unit_of_measure":"...","disaggregation":"...","data_source_and_frequency":"..."}}],"means_of_verification":"...","assumptions":"..."}},
{{"id":"outcome-1","level":"outcome","parent_id":"impact-1","intervention_logic":"...","indicators":[{{"indicator_title":"...","baseline_value":"...","target_value":"...","unit_of_measure":"...","disaggregation":"...","data_source_and_frequency":"..."}}],"means_of_verification":"...","assumptions":"..."}},
{{"id":"output-1","level":"output","parent_id":"outcome-1","intervention_logic":"...","indicators":[{{"indicator_title":"...","baseline_value":"...","target_value":"...","unit_of_measure":"...","disaggregation":"...","data_source_and_frequency":"..."}}],"means_of_verification":"...","assumptions":"..."}},
{{"id":"activity-1","level":"activity","parent_id":"output-1","intervention_logic":"...","indicators":[{{"indicator_title":"...","baseline_value":"...","target_value":"...","unit_of_measure":"...","disaggregation":"...","data_source_and_frequency":"..."}}],"means_of_verification":"...","assumptions":"..."}}],
"gantt":[{{"activity_id":"activity-1","months":[1,2,3]}}],"draft_notes":["..."]}}
Use short sequential IDs, preserve parent relationships, and do not invent donor commitments. If current_technical_design contains rows, preserve their IDs, parent links and user text, and complete or improve their indicators instead of deleting them. Draft at least one complete SMART indicator for every row; for outcome/output rows all six indicator fields are mandatory. Use clearly labelled assumptions when a baseline is unknown (for example, "To be established in inception survey") rather than leaving fields blank.
Keep every narrative field under 500 characters and return at most 2 indicators per row.
Return exactly 1 impact, 1 outcome, 2 outputs, and 2 activities; do not add extra rows.
Do not include markdown, source lists, or explanatory text outside the JSON."""
    raw, _ = _run_generator_with_tools(prompt, json.dumps(source, ensure_ascii=False), "3", max_tokens=7000)
    parsed = _json(raw)
    if not isinstance(parsed.get("logframe"), list): parsed["logframe"] = []
    _normalize_indicator_drafts(parsed["logframe"])
    if not isinstance(parsed.get("gantt"), list): parsed["gantt"] = []
    if not isinstance(parsed.get("hypotheses"), list): parsed["hypotheses"] = []
    parsed["grant_months"] = int(parsed.get("grant_months") or 12)
    parsed.setdefault("toc_narrative", "")
    parsed.setdefault("draft_notes", [])
    return parsed


def generate_step_four_draft(setup: dict) -> dict:
    """Create an editable budget, risk and compliance draft for Step 4."""
    donor = DONOR_PROFILES.get(setup.get("donor"), DONOR_PROFILES["generic"])
    source = {
        "locked_setup": {key: setup.get(key, "") for key in ("project_title", "country", "donor", "budget_amount", "budget_currency")},
        "technical_design": setup.get("technical_data", {}),
        "current_financial_data": setup.get("financial_data", {}),
        "donor_rules": donor.get("financial_rules", {}),
        "call_document": str(setup.get("reference_text", ""))[:10000],
    }
    prompt = f"""{donor.get('prompt_directive', '')}
Create an editable Step 4 commitments and financials draft. Return JSON only:
{{"budget_items":[{{"item_code":"1.1","category":1,"description":"...","unit_type":"month","quantity":1,"unit_cost":0,"duration_frequency":1,"donor_grant_share":0,"co_financing_share":0}}],"risks":[{{"category":"Operational","risk_description":"...","likelihood":3,"impact":4,"mitigation_strategy":"..."}}],"psea_signoff":false,"sphere_standards_narrative":"...","draft_notes":["..."]}}
Use 4-8 realistic itemized lines tied to the activities, valid categories 1-5, positive quantities and costs, and keep category 5 indirect overhead within the donor ceiling. Add 3-5 risks with actionable mitigation. Do not claim that a policy is signed: leave psea_signoff false and draft the commitment text for user confirmation. Preserve current_financial_data values when present. Never invent donor commitments."""
    raw, _ = _run_generator_with_tools(prompt, json.dumps(source, ensure_ascii=False), "4", max_tokens=5000)
    parsed = _json(raw)
    if not isinstance(parsed.get("budget_items"), list): parsed["budget_items"] = []
    if not isinstance(parsed.get("risks"), list): parsed["risks"] = []
    parsed["psea_signoff"] = bool(parsed.get("psea_signoff"))
    parsed.setdefault("sphere_standards_narrative", "")
    parsed.setdefault("draft_notes", [])
    return parsed


def analyze_step_one(setup, rules):
    """Generate a normalized intent then verify it blind, capped at three refinements."""
    donor = DONOR_PROFILES[setup["donor"]]
    directive = donor.get("prompt_directive", "")
    generator_input = json.dumps(
        {
            "project_title": setup["project_title"],
            "country": setup["country"],
            "region": setup["region"],
            "donor": donor["label"],
            "budget": f"{setup['budget_amount']} {setup['budget_currency']}",
            "executive_intent": setup["executive_intent"],
            "sectors": setup["sectors"],
            "call_document": setup.get("reference_text", "")[:12000],
        },
        ensure_ascii=False,
    )
    generator_prompt = (
        f"{directive}\n\n"
        "Normalize this project setup into concise donor-ready intent text. "
        "Use search tools to find current data about the crisis context before writing. "
        'Return JSON only: {"normalized_intent":"..."}. '
        "Preserve facts; do not invent data."
    )
    raw, sources = _run_generator_with_tools(generator_prompt, generator_input, "1")
    normalized = _json(raw)["normalized_intent"]

    step1_rules = donor.get("section_rules", {}).get("step1_executive_intent", {})
    mandatory = step1_rules.get("mandatory_tokens", [])
    verifier_prompt = (
        f"You are an isolated Blind Compliance Auditor for {donor['label']} ({donor.get('framework_standard', '')}). "
        f"You receive ONLY normalized text and rules, never generator prompts or history. "
        f"Evaluate against these MANDATORY CONSTRAINTS:\n"
        f"- Required keyword concepts: {mandatory}\n"
        f"- Policy Directives: {directive}\n"
        f"- Deterministic violations from rules engine: {rules['violations']}\n"
        f'Return JSON only: {{"is_valid":true,"donor_compliance_score":0-100,"critique_notes":[...],"suggested_improvements":[...]}}.'
    )
    result = None
    for iteration in range(MAX_REFINEMENTS):
        blind_input = json.dumps(
            {
                "normalized_intent": normalized,
                "donor_rules": donor["step_1_advisories"],
                "deterministic_violations": rules["violations"],
            },
            ensure_ascii=False,
        )
        result = _json(
            _model(0.1, max_tokens=1800)
            .invoke([SystemMessage(content=verifier_prompt), HumanMessage(content=blind_input)])
            .content
        )
        if result.get("is_valid") and int(result.get("donor_compliance_score", 0)) >= 70:
            break
        if iteration < MAX_REFINEMENTS - 1:
            refine = 'Refine this normalized intent using these verifier corrections. Return JSON only: {"normalized_intent":"..."}.'
            normalized = _json(
                _model(0.2, max_tokens=1800)
                .invoke(
                    [
                        SystemMessage(content=refine),
                        HumanMessage(
                            content=json.dumps(
                                {
                                    "normalized_intent": normalized,
                                    "corrections": result.get("suggested_improvements", []),
                                }
                            )
                        ),
                    ]
                )
                .content
            )["normalized_intent"]
    result.update(
        {
            "step_id": 1,
            "iterations": iteration + 1,
            "normalized_intent": normalized,
            "sources": sources,
            "analyzed_at": time.time(),
        }
    )
    return result


# ── Step 2 ────────────────────────────────────────────────────────────────────


def analyze_step_two(setup, step2, rules):
    """Synthesize Step 2 then verify only the synthesized text and rule manifest."""
    donor = DONOR_PROFILES[setup["donor"]]
    directive = donor.get("prompt_directive", "")
    source = {
        "step_1_contract": {
            key: setup[key]
            for key in (
                "project_title",
                "country",
                "region",
                "donor",
                "budget_amount",
                "budget_currency",
                "executive_intent",
                "sectors",
            )
        },
        "step_2_draft": {
            key: step2[key] for key in ("humanitarian_context", "needs_assessment", "strategic_justification")
        },
    }
    generator_prompt = (
        f"{directive}\n\n"
        "Create a faithful donor-ready normalization of these Step 2 narratives. "
        "Use search tools (search_sitreps, search_knowledge_base, hdx_get_refugees, hdx_get_funding, brave_web_search) "
        "to gather real, current data about the humanitarian situation. "
        "Include specific numbers (displacement figures, casualty counts, funding gaps) from real sources. "
        "Every factual claim must cite a source using: [Source: Title](URL). "
        "Preserve facts and do not invent statistics. "
        'Return JSON only: {"narratives":{"humanitarian_context":"...","needs_assessment":"...","strategic_justification":"..."},"sources":[{"title":"...","url":"..."}]}.'
    )
    raw, sources = _run_generator_with_tools(generator_prompt, json.dumps(source, ensure_ascii=False), "2")
    parsed = _json(raw)
    narratives = parsed.get("narratives", parsed)
    if not isinstance(narratives, dict):
        narratives = {"humanitarian_context": str(narratives)}
    sources = parsed.get("sources", sources)

    step2_ctx_rules = donor.get("section_rules", {}).get("step2_humanitarian_context", {})
    step2_na_rules = donor.get("section_rules", {}).get("step2_needs_assessment", {})
    step2_sj_rules = donor.get("section_rules", {}).get("step2_strategic_justification", {})
    all_mandatory = (
        step2_ctx_rules.get("mandatory_tokens", [])
        + step2_na_rules.get("mandatory_tokens", [])
        + step2_sj_rules.get("mandatory_tokens", [])
    )
    verifier_prompt = (
        f"You are an isolated Blind Compliance Auditor for {donor['label']} ({donor.get('framework_standard', '')}). "
        f"You receive ONLY normalized narratives and an explicit rule manifest, never generator prompts or history. "
        f"Evaluate against these MANDATORY CONSTRAINTS:\n"
        f"- Required keyword concepts across narratives: {all_mandatory}\n"
        f"- Policy Directives: {directive}\n"
        f'Return JSON only: {{"is_valid":true,"donor_compliance_score":0-100,"critique_notes":[...],"suggested_improvements":[...]}}.'
    )
    result = None
    for iteration in range(MAX_REFINEMENTS):
        blind_input = {
            "normalized_narratives": narratives,
            "donor_rule_manifest": {
                "donor": donor["label"],
                "max_characters_per_section": 4000,
                "deterministic_violations": rules["violations"],
                "beneficiary_summary": rules["beneficiary_summary"],
            },
        }
        result = _json(
            _model(0.1, max_tokens=1800)
            .invoke(
                [
                    SystemMessage(content=verifier_prompt),
                    HumanMessage(content=json.dumps(blind_input, ensure_ascii=False)),
                ]
            )
            .content
        )
        if result.get("is_valid") and int(result.get("donor_compliance_score", 0)) >= 70:
            break
        if iteration < MAX_REFINEMENTS - 1:
            refine_prompt = """Revise the normalized narratives using only these corrections. Do not invent facts. Return JSON only: {\"narratives\":{\"humanitarian_context\":\"...\",\"needs_assessment\":\"...\",\"strategic_justification\":\"...\"}}."""
            narratives = _json(
                _model(0.2, max_tokens=1800)
                .invoke(
                    [
                        SystemMessage(content=refine_prompt),
                        HumanMessage(
                            content=json.dumps(
                                {"narratives": narratives, "corrections": result.get("suggested_improvements", [])},
                                ensure_ascii=False,
                            )
                        ),
                    ]
                )
                .content
            )["narratives"]
    result.update(
        {
            "step_id": 2,
            "iterations": iteration + 1,
            "normalized_narratives": narratives,
            "sources": sources,
            "analyzed_at": time.time(),
        }
    )
    return result


# ── Step 3 ────────────────────────────────────────────────────────────────────


def analyze_step_three(setup, step2, step3, rules):
    """Synthesize technical logic, then verify it without exposing generator history."""
    donor = DONOR_PROFILES[setup["donor"]]
    directive = donor.get("prompt_directive", "")
    source = {
        "step_1_contract": {key: setup[key] for key in ("project_title", "country", "donor", "executive_intent")},
        "step_2_contract": step2,
        "step_3_draft": step3,
    }
    generator_prompt = (
        f"{directive}\n\n"
        "Normalize this technical approach into a coherent logframe and Theory of Change summary. "
        "Use search_knowledge_base to find indicator benchmarks and data sources relevant to the crisis context. "
        "Preserve all facts and IDs; do not invent evidence. "
        'Return JSON only: {"technical_summary":"...","sources":[{"title":"...","url":"..."}]}.'
    )
    raw, sources = _run_generator_with_tools(generator_prompt, json.dumps(source, ensure_ascii=False), "3")
    parsed = _json(raw)
    summary = parsed.get("technical_summary", str(parsed))
    sources = parsed.get("sources", sources)

    lf_rules = donor.get("logframe_rules", {})
    verifier_prompt = (
        f"You are an isolated Blind Compliance Auditor for {donor['label']} ({donor.get('framework_standard', '')}). "
        f"You receive ONLY a technical summary and a rule manifest, never generator prompts or history. "
        f"Evaluate vertical logic, horizontal logic and SMART indicator quality against these constraints:\n"
        f"- Max outcomes: {lf_rules.get('max_outcomes', 3)}\n"
        f"- HRP alignment required: {lf_rules.get('require_hrp_alignment', False)}\n"
        f"- ITT/PIRS for custom indicators: {lf_rules.get('custom_indicator_itt_pirs_required', False)}\n"
        f"- Policy Directives: {directive}\n"
        f'Return JSON only: {{"is_valid":true,"donor_compliance_score":0-100,"critique_notes":[...],"suggested_improvements":[...]}}.'
    )
    result = None
    for iteration in range(MAX_REFINEMENTS):
        blind = {
            "technical_summary": summary,
            "donor_rule_manifest": {
                "donor": donor["label"],
                "deterministic_violations": rules["violations"],
                "logframe_metrics": rules["logframe_metrics"],
            },
        }
        result = _json(
            _model(0.1, max_tokens=1800)
            .invoke(
                [SystemMessage(content=verifier_prompt), HumanMessage(content=json.dumps(blind, ensure_ascii=False))]
            )
            .content
        )
        if result.get("is_valid") and int(result.get("donor_compliance_score", 0)) >= 70:
            break
        if iteration < MAX_REFINEMENTS - 1:
            refine = 'Refine this technical summary using only the listed corrections. Return JSON only: {"technical_summary":"..."}.'
            summary = _json(
                _model(0.2, max_tokens=1800)
                .invoke(
                    [
                        SystemMessage(content=refine),
                        HumanMessage(
                            content=json.dumps(
                                {"technical_summary": summary, "corrections": result.get("suggested_improvements", [])}
                            )
                        ),
                    ]
                )
                .content
            )["technical_summary"]
    result.update(
        {
            "step_id": 3,
            "iterations": iteration + 1,
            "technical_summary": summary,
            "sources": sources,
            "analyzed_at": time.time(),
        }
    )
    return result
