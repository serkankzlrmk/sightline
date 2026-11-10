"""Tests for the LLM observability layer (obs.db telemetry + admin API).

These tests never touch the network and never call a real LLM: they exercise
the telemetry store directly and the admin read routes with dev auth bypass
(enabled by tests/conftest.py).
"""

import time

import pytest


@pytest.fixture()
def obs_db(tmp_path, monkeypatch):
    """Point OBS_DB_PATH at a throwaway DB and reset the init cache."""
    import config
    from observability import store

    monkeypatch.setattr(config, "OBS_DB_PATH", tmp_path / "obs.db", raising=False)
    monkeypatch.setattr(config, "OBS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "OBS_RETENTION_DAYS", 90, raising=False)
    store.reset_for_tests()
    store.init_obs_db(force=True)
    yield store
    store.reset_for_tests()


def _turn(**overrides):
    now = time.time()
    base = {
        "turn_id": overrides.pop("turn_id", "turn-test-1"),
        "uid": "u1",
        "chat_id": "c1",
        "model_key": "flash",
        "model_id": "google/gemini-3.8-flash",
        "mode": "analyst",
        "started_at": now - 1,
        "finished_at": now,
        "latency_ms": 1200,
        "total_ms": 1500,
        "status": "ok",
        "iterations": 2,
        "tokens_in": 100,
        "tokens_out": 50,
        "cost": 0.001,
        "groups": {"ReliefWeb": 1},
        "answer": "Flooding affected 1,200 people [1][2].",
    }
    base.update(overrides)
    return base


def test_metrics_citations_and_no_answer():
    from observability.metrics import answer_signals, citation_count, extract_citations, is_no_answer

    assert extract_citations("a [1] b [2] c [1]") == [1, 2, 1]
    assert citation_count("a [1] b [2] c [1]") == 2
    assert is_no_answer("The sources do not contain enough information about this.")
    assert not is_no_answer("Flooding affected 1,200 people [1].")

    signals = answer_signals("Answer [3][4].")
    assert signals["citations"] == 2
    assert signals["has_citations"] is True
    assert signals["no_answer"] is False


def test_record_turn_tools_and_aggregates(obs_db):
    store = obs_db
    store.record_chat_turn(
        _turn(),
        tools=[
            {
                "tool": "search_sitreps",
                "group": "ReliefWeb",
                "server": "native",
                "status": "ok",
                "duration_ms": 300,
                "result_chars": 900,
                "summary": "3 reports",
            },
            {
                "tool": "search_papers",
                "group": "MCP",
                "server": "arxiv",
                "status": "error",
                "duration_ms": 12000,
                "result_chars": 25,
                "summary": "Error: timeout",
            },
        ],
    )
    store.record_chat_turn(
        _turn(
            turn_id="turn-test-2",
            uid="u2",
            status="error",
            error="boom",
            latency_ms=0,
            tokens_in=0,
            tokens_out=0,
            cost=0.0,
            answer="",
        )
    )

    s = store.summary(days=7)
    assert s["turns"] == 2
    assert s["ok"] == 1
    assert s["errors"] == 1
    assert s["users"] == 2
    assert s["tool_calls"] == 2
    assert s["tool_errors"] == 1
    assert s["citation_rate"] == 1.0
    assert s["error_rate"] == 0.5

    tools = store.tool_stats(days=7)
    assert {t["tool"] for t in tools} == {"search_sitreps", "search_papers"}
    arxiv = next(t for t in tools if t["tool"] == "search_papers")
    assert arxiv["server"] == "arxiv"
    assert arxiv["errors"] == 1

    models = store.model_stats(days=7)
    assert models[0]["model_key"] == "flash"
    assert models[0]["turns"] == 2

    turns = store.recent_turns(limit=10)
    assert len(turns) == 2
    assert turns[0]["turn_id"] == "turn-test-2"

    detail = store.turn_detail("turn-test-1")
    assert detail is not None
    assert len(detail["tools"]) == 2
    assert detail["turn"]["groups"] == {"ReliefWeb": 1}

    series = store.timeseries(days=3)
    assert len(series) == 3
    assert sum(day["turns"] for day in series) == 2


def test_prune_removes_old_turns(obs_db):
    store = obs_db
    old = time.time() - 10 * 86400
    store.record_chat_turn(_turn(turn_id="old-turn", started_at=old))
    store.record_chat_turn(_turn(turn_id="new-turn"))

    deleted = store.prune(days=5)
    assert deleted == 1
    remaining = store.recent_turns(limit=10)
    assert [t["turn_id"] for t in remaining] == ["new-turn"]


def test_feedback_summary(obs_db):
    store = obs_db
    store.record_feedback(1, uid="u1", turn_id="turn-test-1")
    store.record_feedback(-1, uid="u2", turn_id="turn-test-2")
    store.record_feedback(1, uid="u3", turn_id="turn-test-3")
    summary = store.feedback_summary(days=7)
    assert summary == {"up": 2, "down": 1, "total": 3, "positive_rate": round(2 / 3, 4)}


def test_disabled_store_is_a_noop(obs_db, monkeypatch):
    import config

    monkeypatch.setattr(config, "OBS_ENABLED", False, raising=False)
    assert obs_db.record_chat_turn(_turn(turn_id="disabled-turn")) is False
    assert obs_db.summary(days=7)["turns"] == 0


def test_health_reports_db_and_mcp(obs_db):
    info = obs_db.health()
    assert info["enabled"] is True
    assert info["db_exists"] is True
    assert "mcp" in info
    assert isinstance(info["mcp"], dict)


def test_mcp_ready_event_exists():
    """Regression: relief_agent waits on this event — it must exist in mcp_integration."""
    import mcp_integration

    assert hasattr(mcp_integration, "_mcp_ready_event")
    assert isinstance(mcp_integration.MCP_TOOL_SERVERS, dict)
    assert isinstance(mcp_integration.MCP_READY_AT, (float, type(None)))


def test_admin_obs_routes(obs_db):
    """Admin routes are reachable under dev auth bypass and return JSON."""
    import server

    obs_db.record_chat_turn(_turn())
    client = server.app.test_client()

    for path in (
        "/api/admin/obs/health",
        "/api/admin/obs/summary?days=7",
        "/api/admin/obs/timeseries?days=7",
        "/api/admin/obs/tools?days=7",
        "/api/admin/obs/models?days=7",
        "/api/admin/obs/turns?limit=5",
        "/api/admin/obs/feedback?days=7",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code, response.data[:200])

    detail = client.get("/api/admin/obs/turn/turn-test-1")
    assert detail.status_code == 200
    assert detail.get_json()["turn"]["turn_id"] == "turn-test-1"

    missing = client.get("/api/admin/obs/turn/does-not-exist")
    assert missing.status_code == 404


def test_admin_does_not_consume_daily_api_budget(obs_db):
    """The custom 100/day IP limiter must exempt /api/admin/* (dashboard polling)."""
    import server
    from blueprints.helpers import _api_rate_counts, _api_rate_lock

    with _api_rate_lock:
        _api_rate_counts.clear()

    client = server.app.test_client()
    for _ in range(3):
        assert client.get("/api/admin/obs/summary").status_code == 200

    with _api_rate_lock:
        assert _api_rate_counts == {}


def test_app_shell_contains_observability_panel(obs_db):
    """The admin tab must expose the Observability sub-tab and its containers."""
    import server

    client = server.app.test_client()
    resp = client.get("/app")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8", "ignore")
    assert 'data-admin-tab="obs"' in html
    assert 'id="admin-obs"' in html
    assert 'id="obs-kpi-cards"' in html
    assert 'id="chart-obs-p95"' in html
    assert 'id="obs-eval-table"' in html
    assert 'id="obs-eval-run-btn"' in html
    assert 'id="obs-calibration-line"' in html
    assert 'id="obs-cal-card"' in html
    assert 'id="obs-cal-start"' in html
    assert 'id="obs-cal-submit"' in html


# ── Offline eval scores ──────────────────────────────────────────────────────


def test_record_eval_score_and_recent(obs_db):
    store = obs_db
    assert store.record_eval_score("turn-test-1", 4.5, judge_model="j/m", chat_id="c1", issues=["thin"]) is True
    assert store.record_eval_score("turn-test-2", 2.0, judge_model="j/m", chat_id="c1") is True
    # out-of-range scores are clamped, garbage turn ids refused
    assert store.record_eval_score("turn-test-3", 9.0, judge_model="j/m") is True
    assert store.record_eval_score("", 3.0) is False

    recent = store.eval_recent(days=30, limit=10)
    assert [r["turn_id"] for r in recent] == ["turn-test-3", "turn-test-2", "turn-test-1"]
    t1 = next(r for r in recent if r["turn_id"] == "turn-test-1")
    assert t1["score"] == 4.5 and t1["issues"] == ["thin"]
    clamped = next(r for r in recent if r["turn_id"] == "turn-test-3")
    assert clamped["score"] == 5.0

    low = store.eval_recent(days=30, limit=10, low_only=True)
    assert [r["turn_id"] for r in low] == ["turn-test-2"]

    s = store.eval_summary(days=30)
    assert s["count"] == 3 and s["low_count"] == 1 and s["count"] >= 1
    assert s["distribution"][2] == 1 and s["distribution"][4] == 1 and s["distribution"][5] == 1


def test_admin_eval_route(obs_db):
    import server

    obs_db.record_eval_score("turn-test-1", 4.0, judge_model="j/m", chat_id="c1")
    obs_db.record_eval_score("turn-test-2", 2.0, judge_model="j/m")

    client = server.app.test_client()
    resp = client.get("/api/admin/obs/eval?days=30")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"]["count"] == 2
    assert len(body["recent"]) == 2

    low = client.get("/api/admin/obs/eval?days=30&low=1")
    assert low.status_code == 200
    rows = low.get_json()["recent"]
    assert [r["turn_id"] for r in rows] == ["turn-test-2"]

    bad = client.get("/api/admin/obs/eval?days=0")
    assert bad.status_code == 200  # clamped, not an error


# ── Chat-eval integration (tool evidence, retrieval runs, admin trigger) ─────


def test_tool_result_preview_is_persisted(obs_db):
    obs_db.record_chat_turn(
        _turn(),
        tools=[
            {
                "tool": "search_sitreps",
                "group": "ReliefWeb",
                "server": "native",
                "status": "ok",
                "duration_ms": 250,
                "result_chars": 1200,
                "result_preview": "Sudan: 1,200 people displaced in Khartoum [GW-1]",
                "summary": "3 reports",
            }
        ],
    )
    detail = obs_db.turn_detail("turn-test-1")
    assert detail["tools"][0]["result_preview"].startswith("Sudan: 1,200")


def test_retrieval_eval_persists_two_stage_metrics(obs_db):
    result = {
        "k": 10,
        "stage1_k": 50,
        "per_query": [
            {
                "query": "q",
                "recall_at_k": 0.5,
                "recall_at_k_stage1": 1.0,
                "mrr": 1.0,
                "ndcg_at_k": 0.7,
            }
        ],
        "aggregate": {
            "queries": 1,
            "mean_recall_at_k": 0.5,
            "mean_recall_at_stage1": 1.0,
            "mean_mrr": 1.0,
            "mean_ndcg_at_k": 0.7,
        },
    }
    assert obs_db.record_retrieval_eval("gold.json", 10, result, stage1_k=50) is True
    summary = obs_db.eval_retrieval_summary(days=1)
    assert summary["latest"]["gold_path"] == "gold.json"
    assert summary["latest"]["mean_ndcg"] == 0.7
    assert summary["latest"]["mean_recall_stage1"] == 1.0


def test_eval_scores_upsert_keeps_one_row(obs_db):
    assert obs_db.record_eval_score("t1", 2, judge_model="judge/x")
    assert obs_db.record_eval_score("t1", 5, judge_model="judge/x")
    assert obs_db.eval_summary(days=1)["count"] == 1
    assert obs_db.eval_summary(days=1)["avg"] == 5.0


def test_admin_eval_retrieval_endpoint(obs_db):
    import server

    client = server.app.test_client()
    obs_db.record_retrieval_eval(
        "gold.json",
        10,
        {"per_query": [], "aggregate": {"queries": 0}},
        stage1_k=50,
    )
    for path in ("/api/admin/obs/eval", "/api/admin/obs/eval/retrieval"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.data[:200])


def test_admin_eval_run_is_bounded_and_backgrounded(obs_db, monkeypatch):
    import blueprints.obs_bp as obs_bp
    import server

    called = {}

    def fake_job(job_id, params):
        called["job_id"] = job_id
        called["params"] = params

    monkeypatch.setattr(obs_bp, "_run_eval_job", fake_job)
    client = server.app.test_client()
    response = client.post(
        "/api/admin/obs/eval/run",
        json={"sample": 99, "samples": 99, "days": 999},
    )
    assert response.status_code == 202
    body = response.get_json()
    assert body["params"]["sample"] == 25  # clamped
    assert body["params"]["samples"] == 3
    assert body["params"]["days"] == 90

    status = client.get(f"/api/admin/obs/eval/run/status/{body['job_id']}")
    assert status.status_code == 200
    assert called["params"]["sample"] == 25

    missing = client.get("/api/admin/obs/eval/run/status/does-not-exist")
    assert missing.status_code == 404


# ── Chat 👍/👎 feedback ─────────────────────────────────────────────────────


def test_feedback_upsert_and_lookup(obs_db):
    assert obs_db.record_feedback(1, uid="u1", turn_id="t1") is True
    assert obs_db.record_feedback(-1, uid="u1", turn_id="t1") is True  # toggles update
    fb = obs_db.feedback_for_turns("u1", ["t1"])
    assert fb["t1"]["rating"] == -1
    assert obs_db.feedback_for_turns("u2", ["t1"]) == {}


def _seed_feedback_chat(tmp_path, monkeypatch, obs_db):
    import sqlite3

    import config

    chats_path = tmp_path / "chats.db"
    conn = sqlite3.connect(str(chats_path))
    conn.executescript(
        """
        CREATE TABLE chats (id TEXT PRIMARY KEY, uid TEXT, title TEXT, created REAL);
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT, role TEXT, content TEXT, ts REAL, meta TEXT DEFAULT '{}'
        );
        """
    )
    conn.execute("INSERT INTO chats VALUES ('c1', 'dev-local', 'T', ?)", (time.time(),))
    conn.execute(
        "INSERT INTO chat_messages (chat_id, role, content, ts, meta) VALUES "
        "('c1','assistant','Answer [1].', ?, '{\"turn_id\":\"t1\"}')",
        (time.time(),),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "CHATS_DB_PATH", chats_path, raising=False)
    # helpers imported CHATS_DB_PATH at module load; point it at the temp DB too.
    import blueprints.helpers as chat_helpers

    monkeypatch.setattr(chat_helpers, "CHATS_DB_PATH", chats_path, raising=False)
    monkeypatch.setattr(chat_helpers, "_chats_schema_ready", False, raising=False)
    obs_db.record_chat_turn(
        {
            "turn_id": "t1",
            "uid": "dev-local",
            "chat_id": "c1",
            "status": "ok",
            "started_at": time.time() - 2,
            "finished_at": time.time() - 1,
        }
    )


def test_chat_feedback_api_and_message_state(obs_db, tmp_path, monkeypatch):
    import server

    _seed_feedback_chat(tmp_path, monkeypatch, obs_db)
    client = server.app.test_client()

    resp = client.post("/api/agent/feedback", json={"turn_id": "t1", "rating": 1})
    assert resp.status_code == 200
    assert resp.get_json()["rating"] == 1

    messages = client.get("/api/agent/chats/c1/messages").get_json()["messages"]
    assert messages[0]["feedback"]["rating"] == 1

    client.post("/api/agent/feedback", json={"turn_id": "t1", "rating": -1})
    messages = client.get("/api/agent/chats/c1/messages").get_json()["messages"]
    assert messages[0]["feedback"]["rating"] == -1

    bad = client.post("/api/agent/feedback", json={"turn_id": "t1", "rating": 0})
    assert bad.status_code == 400
    missing = client.post("/api/agent/feedback", json={"turn_id": "nope", "rating": 1})
    assert missing.status_code == 404


# ── Admin human calibration API (queue / label / score) ─────────────────────


def _seed_calibration_data(obs_db, tmp_path, monkeypatch, n=3):
    import sqlite3

    import config

    chats_path = tmp_path / "calib_chats.db"
    conn = sqlite3.connect(str(chats_path))
    conn.executescript(
        """
        CREATE TABLE chats (id TEXT PRIMARY KEY, uid TEXT, title TEXT, created REAL);
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT, role TEXT, content TEXT, ts REAL, meta TEXT DEFAULT '{}'
        );
        """
    )
    now = time.time()
    for i in range(1, n + 1):
        chat_id = f"c{i}"
        turn_id = f"cal-t{i}"
        conn.execute("INSERT INTO chats VALUES (?, 'dev-local', 'T', ?)", (chat_id, now - 500))
        conn.execute(
            "INSERT INTO chat_messages (chat_id, role, content, ts) VALUES (?, 'user', ?, ?)",
            (chat_id, f"Question {i}?", now - 200),
        )
        conn.execute(
            "INSERT INTO chat_messages (chat_id, role, content, ts) VALUES (?, 'assistant', ?, ?)",
            (chat_id, f"Answer {i} with citation [1].", now - 100),
        )
        obs_db.record_chat_turn(
            {
                "turn_id": turn_id,
                "uid": "dev-local",
                "chat_id": chat_id,
                "status": "ok",
                "model_id": "google/gemini-3.8-flash",
                "started_at": now - 200,
                "finished_at": now - 100,
            }
        )
        obs_db.record_eval_score(turn_id, 3 + (i % 2), judge_model="judge/x")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "CHATS_DB_PATH", chats_path, raising=False)


def test_calibration_queue_is_blind(obs_db, tmp_path, monkeypatch):
    import server

    _seed_calibration_data(obs_db, tmp_path, monkeypatch, n=3)
    client = server.app.test_client()
    data = client.get("/api/admin/obs/calibration/queue?limit=10").get_json()

    assert len(data["queue"]) == 3
    assert data["progress"]["remaining"] == 3
    for item in data["queue"]:
        assert "answer" in item and "question" in item
        assert "score" not in item and "judge_score" not in item  # blind


def test_calibration_label_reveals_and_scores(obs_db, tmp_path, monkeypatch):
    import server

    _seed_calibration_data(obs_db, tmp_path, monkeypatch, n=3)
    client = server.app.test_client()
    queue = client.get("/api/admin/obs/calibration/queue").get_json()["queue"]
    turn_id = queue[0]["turn_id"]

    label = client.post(
        "/api/admin/obs/calibration/label",
        json={"turn_id": turn_id, "score": 4, "notes": "grounded"},
    )
    assert label.status_code == 200
    body = label.get_json()
    assert body["human_score"] == 4
    assert "judge_score" in body  # revealed only after submit
    assert body["progress"]["labeled"] == 1

    # need at least two pairs
    too_few = client.post("/api/admin/obs/calibration/score")
    assert too_few.status_code == 400

    label2 = client.post(
        "/api/admin/obs/calibration/label",
        json={"turn_id": queue[1]["turn_id"], "score": 2},
    )
    assert label2.status_code == 200

    scored = client.post("/api/admin/obs/calibration/score")
    assert scored.status_code == 200
    metrics = scored.get_json()["metrics"]
    assert metrics["n"] == 2
    assert -1.0 <= metrics["qwk"] <= 1.0
    assert obs_db.calibration_summary(days=3650)["human_labeled_turns"] == 2

    # already-labeled turn is no longer in the queue
    remaining = client.get("/api/admin/obs/calibration/queue").get_json()
    assert all(item["turn_id"] != turn_id for item in remaining["queue"])
