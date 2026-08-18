"""
proposal_tools.py — LangChain tools for the proposal wizard agent.

Tools allow the agent to:
- Read proposal context
- Update section drafts
- Approve sections
- Get proposal details
"""

import json
import logging
import sqlite3

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

from config import CHATS_DB_PATH

logger = logging.getLogger(__name__)


def _get_db():
    conn = sqlite3.connect(str(CHATS_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@tool
def get_proposal_details(config: RunnableConfig) -> str:
    """Retrieve the full details of the active proposal, including all sections.

    Use this at the start of a section generation to understand the current proposal state.
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")

    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured in the session."

    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM proposal_setups WHERE id = ? AND uid = ?", (prop_id, uid)).fetchone()

        if not row:
            return "Error: Proposal not found in the database."

        data = {}
        for key in row.keys():
            val = row[key]
            if key in ("context_data", "technical_data", "financial_data", "analysis", "call_brief"):
                try:
                    data[key] = json.loads(val) if val else {}
                except Exception:
                    data[key] = val
            else:
                data[key] = val

        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"get_proposal_details error: {e}")
        return f"Error reading proposal: {str(e)}"
    finally:
        conn.close()


@tool
def get_section_content(section: str, config: RunnableConfig) -> str:
    """Get the current technical data (Step 3) of the active proposal.

    Args:
        section: Ignored — returns the whole technical_data JSON
                 (theory of change, logframe, indicators, activity schedule).
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")

    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured."

    conn = _get_db()
    try:
        row = conn.execute("SELECT technical_data FROM proposal_setups WHERE id = ? AND uid = ?", (prop_id, uid)).fetchone()
        if not row:
            return "Error: Proposal not found."
        td = json.loads(row["technical_data"]) if row["technical_data"] else {}
        return json.dumps(td, indent=2, default=str) if td else "No technical data yet."
    except Exception as e:
        logger.error(f"get_section_content error: {e}")
        return f"Error: {str(e)}"
    finally:
        conn.close()


@tool
def edit_proposal_toc(goal_impact: str, outcome: str, output: str, activity: str, config: RunnableConfig) -> str:
    """Update the Theory of Change (ToC) levels of the active proposal.

    All four levels must be provided as strings:
    - goal_impact: Long-term impact / goal
    - outcome: Specific change in status/behavior
    - output: Direct product of activities
    - activity: Primary action producing the output

    Writes into the setup's technical_data.logframe rows (impact/outcome/
    output/activity levels).
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")

    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured in the session."

    toc_nodes = [
        {"id": "impact-1", "level": "impact", "intervention_logic": goal_impact},
        {"id": "outcome-1", "level": "outcome", "parent_id": "impact-1", "intervention_logic": outcome},
        {"id": "output-1", "level": "output", "parent_id": "outcome-1", "intervention_logic": output},
        {"id": "activity-1", "level": "activity", "parent_id": "output-1", "intervention_logic": activity},
    ]

    conn = _get_db()
    try:
        row = conn.execute("SELECT technical_data FROM proposal_setups WHERE id = ? AND uid = ?", (prop_id, uid)).fetchone()
        if not row:
            return "Error: Proposal not found."
        td = json.loads(row["technical_data"]) if row["technical_data"] else {}
        td["logframe"] = toc_nodes
        conn.execute("UPDATE proposal_setups SET technical_data = ? WHERE id = ? AND uid = ?", (json.dumps(td), prop_id, uid))
        conn.commit()
        return "Success: Theory of Change has been updated in the database."
    except Exception as e:
        logger.error(f"edit_proposal_toc error: {e}")
        return f"Error updating ToC: {str(e)}"
    finally:
        conn.close()


@tool
def edit_proposal_logframe(field: str, text: str, config: RunnableConfig) -> str:
    """Update a specific logframe row's intervention_logic in the active proposal.

    Args:
        field: The logframe row id (e.g. 'impact-1', 'outcome-1', 'output-1', 'activity-1').
        text: The new intervention logic text for that row.
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")

    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured in the session."

    conn = _get_db()
    try:
        row = conn.execute("SELECT technical_data FROM proposal_setups WHERE id = ? AND uid = ?", (prop_id, uid)).fetchone()
        if not row:
            return "Error: Proposal not found."
        td = json.loads(row["technical_data"]) if row["technical_data"] else {}
        lf = td.get("logframe", [])
        target = next((r for r in lf if r.get("id") == field), None)
        if not target:
            return f"Error: Logframe row '{field}' not found."
        target["intervention_logic"] = text
        td["logframe"] = lf
        conn.execute("UPDATE proposal_setups SET technical_data = ? WHERE id = ? AND uid = ?", (json.dumps(td), prop_id, uid))
        conn.commit()
        return f"Success: Logframe row '{field}' updated."
    except Exception as e:
        logger.error(f"edit_proposal_logframe error: {e}")
        return f"Error updating Logframe: {str(e)}"
    finally:
        conn.close()


@tool
def edit_proposal_narrative(narrative: str, config: RunnableConfig) -> str:
    """Update the theory-of-change narrative of the active proposal.

    Args:
        narrative: The new ToC narrative text (technical_data.toc_narrative).
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")

    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured in the session."

    conn = _get_db()
    try:
        row = conn.execute("SELECT technical_data FROM proposal_setups WHERE id = ? AND uid = ?", (prop_id, uid)).fetchone()
        if not row:
            return "Error: Proposal not found."
        td = json.loads(row["technical_data"]) if row["technical_data"] else {}
        td["toc_narrative"] = narrative
        conn.execute("UPDATE proposal_setups SET technical_data = ? WHERE id = ? AND uid = ?", (json.dumps(td), prop_id, uid))
        conn.commit()
        return "Success: Proposal narrative text has been updated."
    except Exception as e:
        logger.error(f"edit_proposal_narrative error: {e}")
        return f"Error updating narrative: {str(e)}"
    finally:
        conn.close()


@tool
def propose_edits(toc: str = None, logframe: str = None, narrative: str = None) -> str:
    """Propose edits to the active proposal without modifying the database directly.

    Args:
        toc: The proposed Theory of Change JSON string, if editing ToC.
        logframe: The proposed Logframe JSON string, if editing Logframe.
        narrative: The proposed markdown narrative text, if editing Narrative.
    """
    return "Success: Edits proposed as drafts."


PROPOSAL_TOOLS = [
    get_proposal_details,
    get_section_content,
    edit_proposal_toc,
    edit_proposal_logframe,
    edit_proposal_narrative,
    propose_edits,
]
