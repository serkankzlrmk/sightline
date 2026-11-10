"""Tests for the aggregate evaluation report."""

import time

import pytest


@pytest.fixture()
def obs_env(tmp_path, monkeypatch):
    import config
    from observability import store

    monkeypatch.setattr(config, "OBS_DB_PATH", tmp_path / "obs.db", raising=False)
    monkeypatch.setattr(config, "OBS_ENABLED", True, raising=False)
    yield store


def _turn(store, turn_id, **kw):
    now = time.time()
    row = {
        "turn_id": turn_id,
        "uid": "u1",
        "chat_id": "c1",
        "model_id": "google/gemini-3.8-flash",
        "started_at": now - 10,
        "finished_at": now,
        "status": "ok",
        "citations": 2,
        "tools_count": 1,
        "cost": 0.01,
        "latency_ms": 1200,
    }
    row.update(kw)
    with store.get_obs_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO turns
            (turn_id, uid, chat_id, model_id, started_at, finished_at, status,
             citations, tools_count, cost, latency_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["turn_id"],
                row["uid"],
                row["chat_id"],
                row["model_id"],
                row["started_at"],
                row["finished_at"],
                row["status"],
                row["citations"],
                row["tools_count"],
                row["cost"],
                row["latency_ms"],
            ),
        )
        conn.commit()


def _score(store, turn_id, score, judge="openai/gpt-5.1"):
    with store.get_obs_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO eval_scores (turn_id, chat_id, judge_model, judge, score, created_at) VALUES (?,?,?,?,?,?)",
            (turn_id, "c1", judge, "offline", score, time.time()),
        )
        conn.commit()


def test_report_collects_instrumented_and_human_metrics(obs_env):
    store = obs_env
    _turn(store, "t1", citations=2, tools_count=1)
    _turn(store, "t2", model_id="", citations=0, tools_count=0, cost=0, latency_ms=0)
    _score(store, "t1", 4)
    _score(store, "t2", 2)
    with store.get_obs_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO human_labels (turn_id, rater, score, notes, rubric_version, created_at) VALUES (?,?,?,?,?,?)",
            ("t1", "human", 4, "", "v1", time.time()),
        )
        conn.execute(
            "INSERT OR REPLACE INTO human_labels (turn_id, rater, score, notes, rubric_version, created_at) VALUES (?,?,?,?,?,?)",
            ("t2", "human", 2, "", "v1", time.time()),
        )
        conn.commit()

    import scripts.eval_report as report

    data = report.collect(days=365, rater="human", min_human=2)
    assert data["count"] == 2
    assert data["signals_n"] == 1
    assert data["citation_rate"] == 1.0
    assert data["human_labels"] == 2
    assert data["human"]["qwk"] == 1.0
    text = report.render(data, "human")
    assert "Judged turns: 2" in text
    assert "Quadratic weighted kappa" in text


def test_report_excludes_synthetic_demo_turns(obs_env):
    store = obs_env
    _turn(store, "t1")
    _score(store, "t1", 4)
    _turn(store, "demo-judge-0", model_id="")
    _score(store, "demo-judge-0", 5)
    import scripts.eval_report as report

    data = report.collect(days=365, rater="human", min_human=20)
    assert data["count"] == 1
    assert "demo-judge-0" not in data["models"]
