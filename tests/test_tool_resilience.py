"""Tests for agent/tool_resilience.py retry + circuit breaker."""

import pytest


class FakeTool:
    def __init__(self, name, results):
        self.name = name
        self._results = iter(results)
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        result = next(self._results)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    import agent.tool_resilience as tr

    monkeypatch.setattr(tr.time, "sleep", lambda *_: None)
    tr.reset_for_tests()
    yield
    tr.reset_for_tests()


def test_retries_transient_error_then_succeeds():
    import agent.tool_resilience as tr

    tool = FakeTool("search", ["Error: timeout after 30s", "ok result"])
    assert tr.invoke_tool(tool, {}, "search") == "ok result"
    assert tool.calls == 2


def test_no_retry_on_auth_error():
    import agent.tool_resilience as tr

    tool = FakeTool("search", ["Error: 401 Unauthorized"])
    assert "401" in tr.invoke_tool(tool, {}, "search")
    assert tool.calls == 1


def test_circuit_opens_after_consecutive_failures():
    import agent.tool_resilience as tr

    tool = FakeTool("dead", [RuntimeError("503 upstream")] * 3)
    for _ in range(3):
        tr.invoke_tool(tool, {}, "dead")
    calls_before = tool.calls
    result = tr.invoke_tool(tool, {}, "dead")
    assert "temporarily disabled" in result
    assert tool.calls == calls_before  # not called while circuit is open


def test_success_resets_failure_counter():
    import agent.tool_resilience as tr

    tool = FakeTool("flaky", [RuntimeError("timeout"), "ok", "ok"])
    assert tr.invoke_tool(tool, {}, "flaky") == "ok"
    assert tr.circuit_open("flaky") is False
