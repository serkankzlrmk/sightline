"""Tests for scripts/backfill_turns.py (historical chats.db → obs.db turns)."""

import sqlite3
import time

import pytest


@pytest.fixture()
def backfill_env(tmp_path, monkeypatch):
    import config
    from observability import store

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
    now = time.time()
    conn.execute("INSERT INTO chats VALUES ('c1', 'u1', 'Sudan', ?)", (now - 500,))
    conn.execute(
        "INSERT INTO chat_messages (chat_id, role, content, ts) VALUES ('c1','user','How many displaced in Sudan?', ?)",
        (now - 400,),
    )
    conn.execute(
        "INSERT INTO chat_messages (chat_id, role, content, ts, meta) VALUES "
        "('c1','assistant','About 1,200 people were displaced in Khartoum [1].', ?, ?)",
        (
            now - 300,
            '{"tools":[{"tool":"search_sitreps","group":"ReliefWeb","status":"ok",'
            '"duration_ms":250,"summary":"3 reports"}],"usage":{"in":100,"out":50},'
            '"cost":0.001,"latency_ms":900,"model":"Flash"}',
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "CHATS_DB_PATH", chats_path, raising=False)
    monkeypatch.setattr(config, "OBS_DB_PATH", tmp_path / "obs.db", raising=False)
    monkeypatch.setattr(config, "OBS_ENABLED", True, raising=False)
    store.reset_for_tests()
    store.init_obs_db(force=True)
    yield store
    store.reset_for_tests()


def test_dry_run_writes_nothing(backfill_env):
    from scripts.backfill_turns import backfill

    report = backfill(days=3650, limit=10, apply=False)
    assert report["found"] == 1
    assert report["written"] == 0
    assert backfill_env.summary(days=3650)["turns"] == 0


def test_apply_creates_turn_with_metadata(backfill_env):
    from scripts.backfill_turns import backfill

    report = backfill(days=3650, limit=10, apply=True)
    assert report["written"] == 1

    turns = backfill_env.recent_turns(limit=10)
    assert len(turns) == 1
    turn = turns[0]
    assert turn["turn_id"].startswith("backfill-")
    assert turn["status"] == "ok"
    assert turn["citations"] == 1
    assert turn["tools_count"] == 1
    assert turn["tokens_in"] == 100

    detail = backfill_env.turn_detail(turn["turn_id"])
    assert detail["tools"][0]["tool"] == "search_sitreps"
    assert detail["turn"]["meta"]["backfilled"] is True


def test_backfill_is_idempotent(backfill_env):
    from scripts.backfill_turns import backfill

    backfill(days=3650, limit=10, apply=True)
    backfill(days=3650, limit=10, apply=True)
    assert backfill_env.summary(days=3650)["turns"] == 1
