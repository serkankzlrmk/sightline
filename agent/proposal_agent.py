"""
proposal_agent.py — Step-based agent for the proposal wizard.

Each section gets:
- A step-specific system prompt (from proposal_prompts.py)
- A restricted set of tools (only what's needed for that section)
- Context from previous sections

The agent runs once per section, returns structured output.
Revision uses streaming for real-time feedback.
"""

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from agent.proposal_prompts import (
    SECTION_ORDER,
    build_user_context,
    get_section_prompt,
)

logger = logging.getLogger(__name__)


def _get_tools_for_step(step: str):
    """Get the restricted tool set for a specific step."""
    prompt_cfg = get_section_prompt(step)
    tool_names = prompt_cfg.get("tools", [])

    if not tool_names:
        return []

    try:
        from agent.relief_agent import all_tools, tools_by_name
    except ImportError:
        logger.warning("Could not import all_tools from relief_agent")
        return []

    selected = []
    for name in tool_names:
        if name in tools_by_name:
            selected.append(tools_by_name[name])
        else:
            logger.warning(f"Tool '{name}' not found for step '{step}'")

    return selected


def _get_model():
    """Get a fresh model instance for proposal generation."""
    try:
        from langchain_openai import ChatOpenAI
        from config import config as _cfg
        return ChatOpenAI(
            model=_cfg.OLLAMA_MODEL,
            base_url=_cfg._LLM_BASE_URL,
            api_key=_cfg._LLM_API_KEY,
            temperature=0.4,
            max_tokens=4096,
            timeout=120,
        )
    except Exception as e:
        logger.error(f"Failed to create model for proposal agent: {e}")
        return None


def _parse_agent_output(response_text: str, step: str) -> dict:
    """Parse the agent's response into structured output."""
    cleaned = (response_text or "").strip()

    if not cleaned:
        return {
            "content": "",
            "sources": [],
            "error": "Agent returned empty response",
        }

    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

    prompt_cfg = get_section_prompt(step)
    output_format = prompt_cfg.get("output_format", "text")

    if output_format == "json":
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                if "content" in parsed:
                    return {
                        "content": parsed.get("content"),
                        "sources": parsed.get("sources", []),
                    }
                else:
                    return {
                        "content": parsed,
                        "sources": [],
                    }
            elif isinstance(parsed, list):
                return {
                    "content": parsed,
                    "sources": [],
                }
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON for step '{step}', returning raw text")

    return {
        "content": cleaned,
        "sources": [],
    }


def generate_section(prop_id: str, step: str, proposal_row: dict, uid: str,
                     instructions: str = "", manual_draft: str = "") -> dict:
    """Generate a proposal section using tools and LLM.

    Args:
        prop_id: Proposal ID
        step: Section step name (e.g. 'background', 'needs_assessment')
        proposal_row: Full proposal row as dict
        uid: User ID
        instructions: User's custom instructions/prompt for this section
        manual_draft: User's own draft text to use as starting point

    Returns:
        {"content": str/dict, "sources": list} or {"error": str}
    """
    try:
        prompt_cfg = get_section_prompt(step)
        system_prompt = prompt_cfg["system"]
        tools = _get_tools_for_step(step)

        user_context = build_user_context(step, proposal_row)

        if instructions:
            user_context += f"\n\n--- USER INSTRUCTIONS ---\n{instructions}"
        if manual_draft:
            user_context += f"\n\n--- USER'S DRAFT (use as starting point, improve and expand) ---\n{manual_draft[:5000]}"

        model = _get_model()
        if model is None:
            return {"error": "LLM model not available"}

        if tools:
            model = model.bind_tools(tools)

            from langgraph.graph import START, StateGraph
            from langgraph.graph.message import MessagesState
            from langgraph.prebuilt import ToolNode

            def llm_call(state: MessagesState):
                messages = state["messages"]
                if not messages or not isinstance(messages[0], SystemMessage):
                    messages = [SystemMessage(content=system_prompt)] + messages
                return {"messages": model.invoke(messages)}

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
                {"messages": [HumanMessage(content=user_context)]},
                config={"recursion_limit": 20},
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
                    if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content and getattr(msg, "name", ""):
                        tool_results.append(f"[{msg.name}]: {msg.content[:500]}")
                if tool_results:
                    response_text = "Based on the research:\n\n" + "\n\n".join(tool_results)
                else:
                    return {"error": "Agent could not generate content for this section. Please try again or revise manually."}

        else:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_context),
            ]
            response = model.invoke(messages)
            response_text = response.content if hasattr(response, "content") else str(response)

        import re as _re2
        response_text = _re2.sub(r"<think>.*?</think>", "", response_text, flags=_re2.DOTALL).strip()
        response_text = _re2.sub(r"\u271d.*?\u271d", "", response_text, flags=_re2.DOTALL).strip()
        if not response_text:
            return {"error": "Agent returned empty response after processing. Please try again or write the section manually."}

        result = _parse_agent_output(response_text, step)

        try:
            from agent.me_reviewer import review_section
            toc_data = proposal_row.get("toc", [])
            logframe_data = proposal_row.get("logframe", {})
            if isinstance(toc_data, str):
                try: toc_data = json.loads(toc_data)
                except (json.JSONDecodeError, TypeError): pass
            if isinstance(logframe_data, str):
                try: logframe_data = json.loads(logframe_data)
                except (json.JSONDecodeError, TypeError): pass

            review = review_section(
                content=result.get("content", ""),
                step=step,
                toc=toc_data if isinstance(toc_data, list) else [],
                logframe=logframe_data if isinstance(logframe_data, dict) else {},
                sources=result.get("sources", []),
            )
            result["quality_score"] = review.get("quality_score")
            result["suggestions"] = review.get("suggestions", [])
            result["overall_score"] = review.get("overall_score", 0)
        except Exception as review_err:
            logger.warning(f"M&E review failed for {step}: {review_err}")

        return result

    except Exception as e:
        logger.error(f"generate_section error: prop={prop_id}, step={step}, err={e}")
        return {"error": f"Section generation failed: {str(e)}"}


def revise_section_stream(prop_id: str, step: str, proposal_row: dict, feedback: str, uid: str):
    """Revise a section via streaming, yielding (chunk_type, chunk_data) tuples.

    Args:
        prop_id: Proposal ID
        step: Section step name
        proposal_row: Full proposal row as dict
        feedback: User's revision feedback
        uid: User ID

    Yields:
        (chunk_type: str, chunk_data: dict) tuples
    """
    try:
        prompt_cfg = get_section_prompt(step)
        system_prompt = prompt_cfg["system"]

        current_content = proposal_row.get(
            _get_db_field(step), ""
        )

        revision_system = (
            f"{system_prompt}\n\n"
            f"You are now revising this section based on user feedback.\n"
            f"Current section content:\n{current_content[:5000]}\n\n"
            f"User feedback: {feedback}\n\n"
            f"Return the COMPLETE revised section (not just the changes). "
            f"Follow the same output format as the original prompt."
        )

        model = _get_model()
        if model is None:
            yield ("error", {"text": "LLM model not available"})
            return

        messages = [
            SystemMessage(content=revision_system),
            HumanMessage(content=f"Please revise the {step} section based on my feedback: {feedback}"),
        ]

        response = model.stream(messages)

        full_text = ""
        for chunk in response:
            if hasattr(chunk, "content") and isinstance(chunk.content, str) and chunk.content:
                full_text += chunk.content
                yield ("token", {"text": chunk.content})

        full_text = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()

        parsed = _parse_agent_output(full_text, step)

        if "error" not in parsed:
            try:
                from agent.proposal_tools import _get_db
                conn = _get_db()
                db_field = _get_db_field(step)
                content = parsed.get("content", "")

                if db_field in ("toc", "logframe", "cover_page", "budget", "mne_framework", "risk_matrix"):
                    if isinstance(content, (list, dict)):
                        stored = json.dumps(content)
                    else:
                        stored = content
                else:
                    stored = content if isinstance(content, str) else str(content)

                conn.execute(
                    f"UPDATE proposals SET {db_field} = ? WHERE id = ?",
                    (stored, prop_id)
                )
                conn.commit()
                conn.close()
            except Exception as db_err:
                logger.warning(f"Failed to save revised section: {db_err}")

            yield ("saved", {"content": parsed.get("content"), "sources": parsed.get("sources", [])})

    except Exception as e:
        logger.error(f"revise_section_stream error: prop={prop_id}, step={step}, err={e}")
        yield ("error", {"text": f"Revision failed: {str(e)}"})


def _get_db_field(step: str) -> str:
    """Map step name to DB field name."""
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
    return field_map.get(step, step)


SECTION_STEPS = SECTION_ORDER
