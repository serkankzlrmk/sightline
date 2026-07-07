"""
proposal_tools.py - LangChain tools for the AI Agent to inspect and edit Proposals.

Allows the agent to view proposal context, update Theory of Change, Logframe matrix,
and narrative text in the SQLite database dynamically.
"""

import json
import logging
import sqlite3
from typing import List, Dict, Any

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
    """Retrieve the full details of the active proposal, including title, country, donor,
    Theory of Change (ToC), Logframe Matrix, and Narrative text.

    Use this tool at the start of a critique or edit session to understand what is currently written.
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")
    
    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured in the session."
        
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT title, country, event, themes, donor, date_from, date_to, toc, logframe, narrative FROM proposals WHERE id = ? AND uid = ?",
            (prop_id, uid)
        ).fetchone()
        
        if not row:
            return "Error: Proposal not found in the database."
            
        data = {
            "title": row["title"],
            "country": row["country"],
            "event": row["event"],
            "themes": json.loads(row["themes"]) if row["themes"].startswith("[") else [row["themes"]],
            "donor": row["donor"],
            "date_from": row["date_from"],
            "date_to": row["date_to"],
            "toc": json.loads(row["toc"]),
            "logframe": json.loads(row["logframe"]),
            "narrative": row["narrative"]
        }
        return json.dumps(data, indent=2)
    except Exception as e:
        logger.error(f"get_proposal_details error: {e}")
        return f"Error reading proposal: {str(e)}"
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
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")
    
    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured in the session."
        
    toc_nodes = [
        {"level": "impact", "text": goal_impact},
        {"level": "outcome", "text": outcome},
        {"level": "output", "text": output},
        {"level": "activity", "text": activity}
    ]
    
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE proposals SET toc = ? WHERE id = ? AND uid = ?",
            (json.dumps(toc_nodes), prop_id, uid)
        )
        conn.commit()
        return "Success: Theory of Change has been updated in the database."
    except Exception as e:
        logger.error(f"edit_proposal_toc error: {e}")
        return f"Error updating ToC: {str(e)}"
    finally:
        conn.close()


@tool
def edit_proposal_logframe(field: str, text: str, config: RunnableConfig) -> str:
    """Update a specific cell/field in the active proposal's Logical Framework matrix.
    
    Args:
        field: The cell key to update. Must be one of:
               - 'goal', 'goal_indicator', 'goal_sources', 'goal_assumptions'
               - 'outcomes', 'outcomes_indicator', 'outcomes_sources', 'outcomes_assumptions'
               - 'outputs', 'outputs_indicator', 'outputs_sources', 'outputs_assumptions'
               - 'activities', 'activities_inputs', 'activities_budget', 'activities_preconditions'
        text: The new text content for that cell.
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")
    
    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured in the session."
        
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT logframe FROM proposals WHERE id = ? AND uid = ?",
            (prop_id, uid)
        ).fetchone()
        
        if not row:
            return "Error: Proposal not found."
            
        lf = json.loads(row["logframe"])
        lf[field] = text
        
        conn.execute(
            "UPDATE proposals SET logframe = ? WHERE id = ? AND uid = ?",
            (json.dumps(lf), prop_id, uid)
        )
        conn.commit()
        return f"Success: Logframe cell '{field}' updated."
    except Exception as e:
        logger.error(f"edit_proposal_logframe error: {e}")
        return f"Error updating Logframe: {str(e)}"
    finally:
        conn.close()


@tool
def edit_proposal_narrative(narrative: str, config: RunnableConfig) -> str:
    """Update the full narrative text draft of the active proposal.
    
    Args:
        narrative: The new markdown-formatted narrative proposal text.
    """
    configurable = config.get("configurable", {})
    uid = configurable.get("uid", "")
    prop_id = configurable.get("proposal_id", "")
    
    if not uid or not prop_id:
        return "Error: No active proposal or user ID configured in the session."
        
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE proposals SET narrative = ? WHERE id = ? AND uid = ?",
            (narrative, prop_id, uid)
        )
        conn.commit()
        return "Success: Proposal narrative text has been updated."
    except Exception as e:
        logger.error(f"edit_proposal_narrative error: {e}")
        return f"Error updating narrative: {str(e)}"
    finally:
        conn.close()

PROPOSAL_TOOLS = [
    get_proposal_details,
    edit_proposal_toc,
    edit_proposal_logframe,
    edit_proposal_narrative
]

@tool
def propose_edits(toc: str = None, logframe: str = None, narrative: str = None) -> str:
    """Propose edits to the active proposal without modifying the database directly.
    
    Args:
        toc: The proposed Theory of Change JSON string, if editing ToC.
        logframe: The proposed Logframe JSON string, if editing Logframe.
        narrative: The proposed markdown narrative text, if editing Narrative.
    """
    # This tool is intercepted by the background review API route to extract drafts.
    return "Success: Edits proposed as drafts."

PROPOSAL_TOOLS = [
    get_proposal_details,
    edit_proposal_toc,
    edit_proposal_logframe,
    edit_proposal_narrative,
    propose_edits
]
