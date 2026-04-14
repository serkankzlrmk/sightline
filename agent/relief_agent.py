"""
ReliefWeb AI Agent - LangGraph based agentic system.
Uses Ollama for local LLM inference with ReliefWeb API tools.
"""

import sys
import os
import json
import logging
from typing import Literal
from datetime import date as _date

# ============================================================================
# ENVIRONMENT SETUP
# ============================================================================
# Suppress TensorRT "nvinfer_10.dll not found" warnings from ONNX Runtime.
# GPU is still used via CUDAExecutionProvider — TensorRT is an optional extra layer.
# Without these, ONNX retries TensorRT on EVERY embedding call (~3 sec delay each).
os.environ["ORT_LOGGING_LEVEL"] = "3"  # ERROR only (suppress INFO/WARNING)
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["ORT_TENSORRT_ENGINE_CACHE_ENABLE"] = "0"
os.environ["ONNXRUNTIME_PROVIDERS"] = "CUDAExecutionProvider,CPUExecutionProvider"

# Suppress SSL warnings (corporate proxy SSL inspection)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Ensure agent/ and project root are on sys.path so imports resolve
from pathlib import Path as _Path
_AGENT_DIR = str(_Path(__file__).parent.resolve())
_ROOT_DIR  = str(_Path(__file__).parent.parent.resolve())
for _p in (_AGENT_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Load configuration
from config import config
from model import get_model, ModelInitializationError

# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# LANGCHAIN IMPORTS
# ============================================================================
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState, START, END

from reliefweb_api import (
    search_sitreps,
    get_sitrep_summary,
    get_report_full_content,
    search_disasters,
    search_disasters_by_date,
    get_latest_headlines,
    get_recent_updates_summary,
    download_and_read_full_pdf,
    download_report_to_folder,
    download_reports_batch,
    convert_report_to_markdown,
    convert_report_to_json,
    parse_reliefweb_url,
    search_sources,
    mcp_langchain_tools,
)

# ============================================================================
# MODEL INITIALIZATION
# ============================================================================
logger.info(f"Initializing model: {config.OLLAMA_MODEL}")

model = get_model()
if model is None:
    logger.critical("Failed to initialize model. System cannot start.")
    sys.exit(1)

tools_by_name = {t.name: t for t in mcp_langchain_tools}
try:
    model_with_tools = model.bind_tools(mcp_langchain_tools)
    logger.info("✓ Model tools bound successfully")
except Exception as e:
    logger.critical(f"Failed to bind tools to model: {e}")
    sys.exit(1)

# ============================================================================
# SYSTEM PROMPT
# ============================================================================

def _build_system_prompt() -> str:
    today = _date.today().isoformat()  # e.g. "2026-04-01"
    return f"""You are a ReliefWeb humanitarian data agent. Your job is to search, read, and download humanitarian reports from ReliefWeb using your tools.

## CURRENT DATE
Today is {today}. Use this date for ALL relative date calculations:
- "son 1 ay" / "last month"  → subtract ~30 days from today
- "son 1 hafta" / "last week" → date_from = 7 days before today
- "2026" → date_from="2026-01-01", date_to="2026-12-31"
- "bu yıl" / "this year" → date_from="{_date.today().year}-01-01"
- "geçen yıl" / "last year" → date_from="{_date.today().year - 1}-01-01", date_to="{_date.today().year - 1}-12-31"

NEVER use dates from 2023 or 2024 unless the user explicitly asks for them.

## YOUR TOOLS

### KNOWLEDGE BASE (local vector DB — use FIRST for questions about existing data)
- **search_knowledge_base(query, n_results, country, source_org)**
  Semantic search over all previously downloaded and ingested reports (ChromaDB).
  Use this BEFORE calling search_sitreps when the user asks questions that might
  be answerable from already-downloaded data.

### SEARCH (ReliefWeb API)
- **search_sitreps(country, query, limit, theme, source_org, date_from, date_to, format_type, language, primary_country, disaster, disaster_type, source_fullname, organization_type)**
  Search reports with advanced filters. Country is OPTIONAL — omit for global search.
  - country: Country name (optional). Omit for global/cross-country search.
  - query: Free-text keyword search
  - theme: 'Health', 'Food and Nutrition', 'Education', 'Shelter and Non-Food Items', 'Water Sanitation Hygiene', 'Protection', 'Logistics and Telecommunications', 'Mine Action'
  - source_org: Organization shortname (e.g., 'UNHCR', 'WFP', 'OCHA', 'WHO')
  - source_fullname: Full organization name when shortname is unknown (e.g., 'Turkish Red Crescent Society')
  - organization_type: Filter by org type: 'International NGO', 'National NGO', 'Government', 'United Nations', 'Red Cross / Red Crescent', 'International Organization'
  - date_from / date_to: 'YYYY-MM-DD' format
  - format_type: 'Situation Report', 'News and Press Release', 'Assessment', 'Appeal', 'Map', 'Infographic', 'Analysis'
  - language: 'en', 'ar', 'fr', 'es'
  - primary_country: Filter by primary country (for multi-country reports)
  - disaster: Filter by disaster name
  - disaster_type: 'Earthquake', 'Flood', 'Drought', 'Epidemic', 'Cyclone', 'Complex Emergency', 'Food Insecurity', etc.

- **search_disasters(country, status, limit)**
  Search disasters. status: 'ongoing', 'past'

- **get_latest_headlines(limit)**
  Latest global humanitarian headlines

- **get_recent_updates_summary(days)**
  Summary of updates from last N days

### URL PARSING
- **parse_reliefweb_url(url)**
  Paste any ReliefWeb URL → automatically fetches report metadata and excerpt.
  Supported: reliefweb.int/report/..., reliefweb.int/node/..., api.reliefweb.int/v2/reports/...

### SOURCE DISCOVERY
- **search_sources(query, country, org_type, limit)**
  Search for organizations/sources by name. Useful when the user mentions an org
  by local name (e.g., "Kızılay") and you need to find the official shortname.
  - org_type: 'International NGO', 'National NGO', 'Government', 'United Nations', 'Red Cross / Red Crescent', etc.

### READ CONTENT
- **get_sitrep_summary(report_id)**
  Short summary (~700 chars) of a specific report

- **get_report_full_content(report_id)**
  Full body text of a specific report

### DOWNLOAD + INGEST (auto-deduplicates)
- **download_report_to_folder(report_id, output_dir)**
  Download one report and auto-ingest into local DB.

- **download_reports_batch(report_ids, output_dir)**
  Download multiple reports. Checks DB first — only downloads NEW reports.

- **download_and_read_full_pdf(report_id)**
  Download and read PDF content directly (in-context, not saved).

- **convert_report_to_markdown(report_id)**
  Convert report content to Markdown format

## BEHAVIOR RULES

1. **Always use tools** — never make up report titles, IDs, or content.
2. **Questions about already-downloaded data** → use search_knowledge_base FIRST.
3. **When user asks to search AND download** (e.g. "bul ve indir", "getir"):
   → search_sitreps → then IMMEDIATELY download_reports_batch with ALL IDs.
4. **When user pastes a ReliefWeb URL** → use parse_reliefweb_url to fetch it.
5. **When user mentions an organization by local/informal name** (e.g. "Kızılay", "Ärzte ohne Grenzen"):
   → use search_sources to find the correct shortname, then use it in search_sitreps.
6. **Global/cross-country search**: If user doesn't specify a country, search_sitreps WITHOUT country.
7. **Download deduplication**: download tools auto-skip existing reports.
8. **Parse natural language filters**:
   - "UNHCR" → source_org="UNHCR"
   - "sağlık" / "health" → theme="Health"
   - "deprem" / "earthquake" → disaster_type="Earthquake"
   - "rapor" → format_type="Situation Report"
   - "Arapça" / "Arabic" → language="ar"
   - "Kızılhaç" / "Red Cross" → organization_type="Red Cross / Red Crescent"
   - "hükümet" / "government" → organization_type="Government"
   - "2025 sonrası" → date_from="2025-01-01"
9. **After downloading**, report: downloaded vs skipped count, file locations, PDF availability.
10. **Multi-turn**: Remember previously found report IDs for follow-up requests.

## RESPONSE FORMAT
- Be concise and factual
- List reports as numbered items with title, date, source, ID
- After downloads: show downloaded / skipped breakdown
- If a filter returns 0 results, suggest relaxing the filter
- For KB search results: show title, date, similarity score, and relevant excerpt
"""


# ============================================================================
# LANGGRAPH AGENT NODES
# ============================================================================

def llm_call(state: MessagesState):
    """LLM node: decides which tools to call or generates final response."""
    messages = [SystemMessage(content=_build_system_prompt())] + state["messages"]
    response = model_with_tools.invoke(messages)
    return {"messages": [response]}


def tool_node(state: MessagesState):
    """Tool execution node: runs all requested tools and returns results."""
    results = []
    for tool_call in state["messages"][-1].tool_calls:
        tool_name = tool_call["name"]
        print(f"  [tool] {tool_name}({', '.join(f'{k}={v!r}' for k, v in tool_call['args'].items())})")
        tool_fn = tools_by_name[tool_name]
        try:
            observation = tool_fn.invoke(tool_call["args"])
        except Exception as e:
            observation = f"Error: {e}"
        results.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
    return {"messages": results}


def should_continue(state: MessagesState) -> Literal["tool_node", "__end__"]:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tool_node"
    return "__end__"


# Build the graph
_builder = StateGraph(MessagesState)
_builder.add_node("llm_call", llm_call)
_builder.add_node("tool_node", tool_node)
_builder.add_edge(START, "llm_call")
_builder.add_conditional_edges("llm_call", should_continue, ["tool_node", "__end__"])
_builder.add_edge("tool_node", "llm_call")
relief_agent = _builder.compile()

_INVOKE_CONFIG = {"recursion_limit": 25}  # max tool-call rounds per turn


# ============================================================================
# CONVERSATIONAL CLI
# ============================================================================

def run_conversational_agent():
    """Multi-turn conversational CLI. State is preserved across turns."""
    conversation_history = []

    print("=" * 70)
    print("RELIEFWEB CONVERSATIONAL AGENT")
    print("=" * 70)
    print(f"Model: {ACTIVE_MODEL}")
    print("Powered by: OpenRouter + ReliefWeb API")
    print()
    print("Examples:")
    print('  "Sudan health raporlarini getir"')
    print('  "UNHCR\'den 2026 sonrasi Syria raporlari"')
    print('  "Pakistan floods - indir"')
    print('  "son bulunan raporlarin ozetini cikar"')
    print('  "exit" to quit')
    print("=" * 70)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCikiliyor...")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("Gorusmek uzere.")
            break

        conversation_history.append(HumanMessage(content=user_input))

        print()
        result = relief_agent.invoke({"messages": conversation_history}, config=_INVOKE_CONFIG)

        # Extract the final AI response
        final_response = None
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                final_response = msg.content
                break

        if final_response:
            print(f"Agent: {final_response}")
        else:
            print("Agent: [No response]")
        print()

        # Update conversation history with full result (preserves tool call context)
        conversation_history = result["messages"]


if __name__ == "__main__":
    run_conversational_agent()

