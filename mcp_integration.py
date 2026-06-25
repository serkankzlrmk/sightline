"""
mcp_integration.py — MCP (Model Context Protocol) server integration for Sightline.

Connects to external MCP servers (arxiv, sequential-thinking, etc.) via stdio
transport, loads their tools as LangChain BaseTool objects, and wraps them in
sync callables so the existing sync agent (relief_agent.py) can use them without
an async refactor.

Pattern:
1. At startup, create a MultiServerMCPClient (async) and load tools.
2. Wrap each async MCP tool in a sync LangChain @tool function.
3. Add wrapped tools to all_tools in relief_agent.py.

Usage in relief_agent.py:
    from mcp_integration import init_mcp_tools, MCP_TOOLS
    init_mcp_tools()  # called at startup
    # MCP_TOOLS is a list of LangChain BaseTool objects (sync)
"""

import asyncio
import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

# MCP tools loaded at startup (sync-wrapped LangChain BaseTool list)
MCP_TOOLS: List = []
_mcp_initialized = False
_mcp_lock = threading.Lock()

# MCP server configurations — populated from config/env at init time
_MCP_SERVERS = {}


def _configure_servers():
    """Build MCP server config dict from environment variables."""
    import os

    servers = {}

    # arxiv-mcp-server (free, keyless — always add if available)
    arxiv_enabled = os.getenv("MCP_ARXIV_ENABLED", "true").lower() == "true"
    if arxiv_enabled:
        servers["arxiv"] = {
            "command": "uvx",
            "args": ["arxiv-mcp-server"],
            "transport": "stdio",
        }

    # sequential-thinking (needs Node.js — only add if enabled)
    seq_enabled = os.getenv("MCP_SEQUENTIAL_THINKING_ENABLED", "false").lower() == "true"
    if seq_enabled:
        servers["sequential_thinking"] = {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
            "transport": "stdio",
        }

    return servers


def _load_mcp_tools_async() -> List:
    """Async: connect to MCP servers and load tools. Returns list of LangChain BaseTool."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    servers = _configure_servers()
    if not servers:
        logger.info("MCP: No servers configured. Skipping MCP integration.")
        return []

    logger.info("MCP: Connecting to %d server(s): %s", len(servers), list(servers.keys()))

    client = MultiServerMCPClient(servers)

    # get_tools() is async — we're inside an async function
    tools = asyncio.get_event_loop().run_until_complete(client.get_tools())

    logger.info("MCP: Loaded %d tools from MCP servers", len(tools))
    for t in tools:
        logger.info("MCP:   - %s: %s", t.name, t.description[:80] if t.description else "")

    return tools


def _wrap_mcp_tool_sync(mcp_tool):
    """Wrap an async MCP LangChain BaseTool in a sync @tool function.

    MCP tools from langchain-mcp-adapters are async (they use asyncio internally).
    The Sightline agent is sync. This wrapper runs the async tool in a new event
    loop on a background thread, blocking until the result is available.
    """
    from langchain_core.tools import tool as tool_decorator

    tool_name = mcp_tool.name
    tool_desc = mcp_tool.description or f"MCP tool: {tool_name}"
    tool_args_schema = getattr(mcp_tool, "args_schema", None)

    @tool_decorator(tool_name, description=tool_desc, args_schema=tool_args_schema)
    def sync_wrapper(**kwargs):
        """Sync wrapper for async MCP tool — runs in background event loop."""
        def run_async():
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(mcp_tool.ainvoke(kwargs))
            finally:
                loop.close()

        # Run in a background thread to avoid blocking the main event loop
        # (gunicorn uses gthread, so we have threads available)
        result_holder = {}

        def _run():
            try:
                result_holder["result"] = run_async()
            except Exception as e:
                result_holder["error"] = e

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=120)  # 2 min timeout per MCP tool call

        if t.is_alive():
            logger.warning("MCP tool %s timed out after 120s", tool_name)
            return f"Error: MCP tool {tool_name} timed out after 120 seconds."

        if "error" in result_holder:
            logger.error("MCP tool %s failed: %s", tool_name, result_holder["error"])
            return f"Error: {result_holder['error']}"

        return result_holder.get("result", "")

    return sync_wrapper


def init_mcp_tools() -> bool:
    """Initialize MCP server connections and load tools.

    Called at startup (from relief_agent.py or server.py). Returns True if any
    MCP tools were loaded. Safe to call multiple times — only initializes once.
    """
    global _mcp_initialized, MCP_TOOLS

    with _mcp_lock:
        if _mcp_initialized:
            return len(MCP_TOOLS) > 0

        try:
            # Run the async tool loader in a fresh event loop
            mcp_tools_raw = asyncio.run(_load_mcp_tools_async_impl())

            if not mcp_tools_raw:
                logger.info("MCP: No tools loaded (servers may not be installed)")
                _mcp_initialized = True
                return False

            # Wrap each async MCP tool in a sync callable
            MCP_TOOLS = [_wrap_mcp_tool_sync(t) for t in mcp_tools_raw]
            _mcp_initialized = True
            logger.info("MCP: %d tools wrapped and ready for sync agent", len(MCP_TOOLS))
            return True

        except Exception as e:
            logger.warning("MCP: Failed to initialize (non-fatal): %s", e)
            _mcp_initialized = True
            return False


async def _load_mcp_tools_async_impl() -> List:
    """Async implementation: connect to MCP servers and load tools."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    servers = _configure_servers()
    if not servers:
        logger.info("MCP: No servers configured. Skipping MCP integration.")
        return []

    logger.info("MCP: Connecting to %d server(s): %s", len(servers), list(servers.keys()))

    client = MultiServerMCPClient(servers)

    tools = await client.get_tools()

    logger.info("MCP: Loaded %d tools from MCP servers", len(tools))
    for t in tools:
        logger.info("MCP:   - %s: %s", t.name, (t.description or "")[:80])

    return tools


def get_mcp_tools() -> List:
    """Return the list of sync-wrapped MCP tools. Empty if not initialized."""
    return MCP_TOOLS