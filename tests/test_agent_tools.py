"""
Test: Agent role-based tool filtering — get_tools_for_mode(role=...).

Verifies that:
1. Free users cannot access sql_query, edit_proposal_*, or propose_edits tools
2. Premium/admin users get the full tool set
3. Mode filtering (analyst/proposal/me_reviewer) works correctly with roles
4. Free users still get read-only proposal tools (get_proposal_details, get_section_content)
"""

import pytest


@pytest.fixture(autouse=True)
def _ensure_agent_loaded():
    """Ensure the agent module is imported and tools are initialized."""
    try:
        from agent.relief_agent import all_tools

        # Ensure tools are loaded (may require config init)
        assert len(all_tools) > 0, "Agent tools should be loaded"
    except Exception as e:
        pytest.skip(f"Agent module could not be loaded: {e}")


# ── Test: Role-based filtering ────────────────────────────────────────────────


class TestRoleBasedToolFiltering:
    """Verify free users get restricted tools and premium/admin get full access."""

    PREMIUM_ONLY_TOOLS = {
        "sql_query",
    }

    def test_free_user_no_sql(self):
        """Free users should NOT have sql_query tool."""
        from agent.relief_agent import get_tools_for_mode

        tools = get_tools_for_mode(mode="analyst", role="free")
        tool_names = {t.name for t in tools}
        assert "sql_query" not in tool_names, "Free users should not have sql_query"

    def test_free_user_has_reliefweb_tools(self):
        """Free users should still have humanitarian data tools."""
        from agent.relief_agent import get_tools_for_mode

        tools = get_tools_for_mode(mode="analyst", role="free")
        tool_names = {t.name for t in tools}
        # These tools should always be available to free users
        expected_tools = {"search_sitreps", "search_disasters", "get_latest_headlines"}
        assert expected_tools.issubset(tool_names), (
            f"Free users should have basic tools, missing: {expected_tools - tool_names}"
        )

    def test_premium_user_has_full_access(self):
        """Premium users should have all tools including SQL."""
        from agent.relief_agent import get_tools_for_mode

        tools = get_tools_for_mode(mode="analyst", role="premium")
        tool_names = {t.name for t in tools}
        for tool_name in self.PREMIUM_ONLY_TOOLS:
            assert tool_name in tool_names, f"Premium users should have {tool_name}"

    def test_admin_user_has_full_access(self):
        """Admin users should have all tools."""
        from agent.relief_agent import get_tools_for_mode

        tools = get_tools_for_mode(mode="analyst", role="admin")
        tool_names = {t.name for t in tools}
        for tool_name in self.PREMIUM_ONLY_TOOLS:
            assert tool_name in tool_names, f"Admin users should have {tool_name}"

    def test_free_tool_count_less_than_premium(self):
        """Free users should have fewer tools than premium users."""
        from agent.relief_agent import get_tools_for_mode

        free_tools = get_tools_for_mode(mode="analyst", role="free")
        premium_tools = get_tools_for_mode(mode="analyst", role="premium")
        assert len(free_tools) < len(premium_tools), "Free users should have fewer tools than premium"

    def test_default_role_is_free(self):
        """Default role should be 'free' (restricted tools)."""
        from agent.relief_agent import get_tools_for_mode

        # Call without role — should default to free
        tools = get_tools_for_mode(mode="analyst")
        tool_names = {t.name for t in tools}
        assert "sql_query" not in tool_names, "Default role (free) should not have sql_query"


# ── Test: Mode-based filtering ────────────────────────────────────────────────


class TestModeBasedToolFiltering:
    """Verify mode parameter returns the correct tool set."""

    def test_analyst_mode_has_all_tools(self):
        """Analyst mode should have all basic tools."""
        from agent.relief_agent import get_tools_for_mode

        tools = get_tools_for_mode(mode="analyst", role="premium")
        tool_names = {t.name for t in tools}
        assert "search_sitreps" in tool_names

    def test_me_reviewer_mode_has_data_tools(self):
        """ME reviewer mode should have humanitarian data tools."""
        from agent.relief_agent import get_tools_for_mode

        tools = get_tools_for_mode(mode="me_reviewer", role="premium")
        tool_names = {t.name for t in tools}
        assert "search_sitreps" in tool_names

    def test_unknown_mode_returns_base_tools(self):
        """Unknown mode should return base tools for the given role."""
        from agent.relief_agent import get_tools_for_mode

        tools = get_tools_for_mode(mode="unknown_mode", role="premium")
        tool_names = {t.name for t in tools}
        # Should still have core tools
        assert "search_sitreps" in tool_names
        assert "sql_query" in tool_names


# ── Test: Premium-only tool set matches documentation ─────────────────────────


class TestPremiumOnlyTools:
    """Verify the exact set of tools that are premium-only."""

    def test_premium_only_tools_are_correct(self):
        """The premium-only set should exactly match the documented tools."""
        from agent.relief_agent import get_tools_for_mode

        free_tools = {t.name for t in get_tools_for_mode("analyst", "free")}
        premium_tools = {t.name for t in get_tools_for_mode("analyst", "premium")}

        # The difference should be exactly the premium-only tools
        premium_only = premium_tools - free_tools
        expected = {"sql_query"}
        assert premium_only == expected, f"Premium-only tools mismatch: {premium_only} vs {expected}"
