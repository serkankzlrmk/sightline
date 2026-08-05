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
import os
import threading
from datetime import date

logger = logging.getLogger(__name__)

# MCP tools loaded at startup (sync-wrapped LangChain BaseTool list)
MCP_TOOLS: list = []
_mcp_initialized = False
_mcp_lock = threading.Lock()

# Brave Search daily rate limiting (protect the $5/month free credit)
_BRAVE_DAILY_LIMIT = int(os.getenv("BRAVE_DAILY_LIMIT", "30"))  # max 30 Brave calls/day
_brave_call_count = {"date": "", "count": 0}
_brave_lock = threading.Lock()


def _check_brave_rate_limit() -> tuple:
    """Check if Brave Search daily limit is reached. Returns (allowed, remaining)."""
    today = date.today().isoformat()
    with _brave_lock:
        if _brave_call_count["date"] != today:
            _brave_call_count["date"] = today
            _brave_call_count["count"] = 0
        if _brave_call_count["count"] >= _BRAVE_DAILY_LIMIT:
            return False, 0
        _brave_call_count["count"] += 1
        remaining = _BRAVE_DAILY_LIMIT - _brave_call_count["count"]
        return True, remaining


# MCP server configurations — populated from config/env at init time
_MCP_SERVERS = {}


def _configure_servers():
    """Build MCP server config dict from environment variables."""
    import os

    # Set cache dirs to /tmp BEFORE any subprocess starts
    # (systemd ProtectSystem=strict makes /opt read-only)
    os.environ["UV_CACHE_DIR"] = "/tmp/uv-cache"
    os.environ["npm_config_cache"] = "/tmp/npm-cache"
    os.makedirs("/tmp/uv-cache", exist_ok=True)
    os.makedirs("/tmp/npm-cache", exist_ok=True)

    servers = {}

    # arxiv-mcp-server (free, keyless — always add if available)
    arxiv_enabled = os.getenv("MCP_ARXIV_ENABLED", "true").lower() == "true"
    if arxiv_enabled:
        servers["arxiv"] = {
            "command": "uvx",
            "args": ["--no-cache", "arxiv-mcp-server"],
            "env": {
                "XDG_CACHE_HOME": "/tmp",
                "HOME": "/tmp",
            },
            "transport": "stdio",
        }

    # sequential-thinking (needs Node.js — only add if enabled)
    seq_enabled = os.getenv("MCP_SEQUENTIAL_THINKING_ENABLED", "true").lower() == "true"
    if seq_enabled:
        servers["sequential_thinking"] = {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
            "env": {
                "npm_config_cache": "/tmp/npm-cache",
                "HOME": "/tmp",
            },
            "transport": "stdio",
        }

    # brave-search (needs Node.js + BRAVE_API_KEY — only add if enabled + key present)
    brave_enabled = os.getenv("MCP_BRAVE_ENABLED", "false").lower() == "true"
    brave_key = os.getenv("BRAVE_API_KEY", "")
    if brave_enabled and brave_key:
        servers["brave_search"] = {
            "command": "npx",
            "args": ["-y", "@brave/brave-search-mcp-server"],
            "env": {
                "BRAVE_API_KEY": brave_key,
                "npm_config_cache": "/tmp/npm-cache",
                "HOME": "/tmp",
            },
            "transport": "stdio",
        }
        logger.info("MCP: Brave Search enabled (API key present)")
    elif brave_enabled and not brave_key:
        logger.warning("MCP: Brave Search enabled but BRAVE_API_KEY not set — skipping")

    return servers


def _load_mcp_tools_async() -> list:
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

    For Brave Search tools, a daily rate limit is enforced to protect the
    free-tier credit budget (default 30 calls/day).
    """
    from langchain_core.tools import tool as tool_decorator

    tool_name = mcp_tool.name
    tool_desc = mcp_tool.description or f"MCP tool: {tool_name}"
    tool_args_schema = getattr(mcp_tool, "args_schema", None)

    # Check if this is a Brave Search tool (rate-limited)
    _is_brave = "brave" in tool_name.lower()

    @tool_decorator(tool_name, description=tool_desc, args_schema=tool_args_schema)
    def sync_wrapper(**kwargs):
        """Sync wrapper for async MCP tool — runs in background event loop."""

        # Brave Search daily rate limit check
        if _is_brave:
            allowed, remaining = _check_brave_rate_limit()
            if not allowed:
                logger.warning("Brave Search daily limit reached (%d/%d)", _BRAVE_DAILY_LIMIT, _BRAVE_DAILY_LIMIT)
                return f"Brave Search daily limit reached ({_BRAVE_DAILY_LIMIT} calls/day). Try again tomorrow or use news_search instead."
            logger.info("Brave Search call: %s (remaining today: %d/%d)", tool_name, remaining, _BRAVE_DAILY_LIMIT)

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

    The actual MCP server connection happens in a background thread to avoid
    blocking the agent startup (MCP subprocess startup can take 30-60s on
    first run when npx/uvx downloads packages).
    """
    global _mcp_initialized, MCP_TOOLS

    with _mcp_lock:
        if _mcp_initialized:
            return len(MCP_TOOLS) > 0
        _mcp_initialized = True  # mark as initialized immediately to prevent re-entry

    # Run MCP init in background thread — non-blocking
    def _bg_init():
        global MCP_TOOLS
        try:
            logger.info("MCP: Background init starting — loading MCP tools...")
            mcp_tools_raw = asyncio.run(_load_mcp_tools_async_impl())
            if mcp_tools_raw:
                MCP_TOOLS = [_wrap_mcp_tool_sync(t) for t in mcp_tools_raw]
                logger.info("MCP: %d tools loaded and ready (background init complete)", len(MCP_TOOLS))
            else:
                logger.info("MCP: No tools loaded (servers may not be installed)")
        except Exception as e:
            logger.warning("MCP: Background init failed (non-fatal): %s", e)
            import traceback

            logger.debug("MCP: Background init traceback: %s", traceback.format_exc())

    t = threading.Thread(target=_bg_init, daemon=True)
    t.start()
    logger.info("MCP: Background initialization thread started (non-blocking)")

    # Return False — tools not ready yet, but will be added when ready
    # The agent will work without MCP tools until they're loaded
    return False


async def _load_mcp_tools_async_impl() -> list:
    """Async implementation: connect to MCP servers and load tools."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    servers = _configure_servers()
    if not servers:
        logger.info("MCP: No servers configured. Skipping MCP integration.")
        return []

    logger.info("MCP: Connecting to %d server(s): %s", len(servers), list(servers.keys()))

    # Load tools from each server separately so one failure doesn't block others
    all_tools = []
    for name, conf in servers.items():
        try:
            logger.info("MCP: Connecting to %s...", name)
            client = MultiServerMCPClient({name: conf})
            tools = await client.get_tools()
            logger.info("MCP: %s — %d tools loaded", name, len(tools))
            all_tools.extend(tools)
        except Exception as e:
            logger.warning("MCP: %s failed (non-fatal, other servers continue): %s", name, e)

    logger.info("MCP: Total %d tools from %d server(s)", len(all_tools), len(servers))
    for t in all_tools:
        logger.info("MCP:   - %s: %s", t.name, (t.description or "")[:80])

    return all_tools


def get_mcp_tools() -> list:
    """Return the list of sync-wrapped MCP tools. Empty if not initialized."""
    return MCP_TOOLS
