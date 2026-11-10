"""Tests for scripts/eval_agent.py — offline LLM-as-a-Judge harness.

No network and no real LLM: the judge is monkeypatched (tests inject a fake
verdict function) or bypassed entirely (parsing-only tests).
"""

import sqlite3
import time

import pytest


@pytest.fixture()
def obs_db(tmp_path, monkeypatch):
    import config
    from observability import store

    monkeypatch.setattr(config, "OBS_DB_PATH", tmp_path / "obs.db", raising=False)
    monkeypatch.setattr(config, "OBS_ENABLED", True, raising=False)
    store.reset_for_tests()
    store.init_obs_db(force=True)
    yield store
    store.reset_for_tests()


@pytest.fixture()
def chats_db(tmp_path, monkeypatch):
    """Throwaway chats.db with one chat and one Q/A message pair."""
    import config

    path = tmp_path / "chats.db"
    conn = sqlite3.connect(str(path))
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
    conn.execute("INSERT INTO chats VALUES ('c1', 'u1', 'T', ?)", (now - 100,))
    conn.execute(
        "INSERT INTO chat_messages (chat_id, role, content, ts) VALUES ('c1','user','How many refugees crossed? [ctx]', ?)",
        (now - 5,),
    )
    conn.execute(
        "INSERT INTO chat_messages (chat_id, role, content, ts) VALUES ('c1','assistant','About 1,200 crossed, per [1].', ?)",
        (now,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "CHATS_DB_PATH", path, raising=False)
    yield path


def _seed_turn(store_obj, days_old: int = 0, chat_id: str = "c1", turn_id: str = "t1", behind_s: float = 0.0):
    now = time.time()
    store_obj.record_chat_turn(
        {
            "turn_id": turn_id,
            "uid": "u1",
            "chat_id": chat_id,
            "model_key": "flash",
            "model_id": "google/gemini-3.8-flash",
            "started_at": now - days_old * 86400 - behind_s - 1,
            "finished_at": now - days_old * 86400 - behind_s,
            "latency_ms": 900,
            "status": "ok",
            "citations": 1,
            "answer_chars": 40,
        }
    )
    return now


# ── Verdict parsing ──────────────────────────────────────────────────────────


def test_parse_verdict_json():
    from scripts.eval_agent import _parse_verdict

    assert _parse_verdict('{"score": 4, "issues": ["thin context"]}') == {"score": 4, "issues": ["thin context"]}


def test_parse_verdict_json_wrapped_in_prose():
    from scripts.eval_agent import _parse_verdict

    text = 'Sure. Verdict: {"score": 2, "issues": ["invented figure", "off topic"]} hope that helps.'
    assert _parse_verdict(text) == {"score": 2, "issues": ["invented figure", "off topic"]}


def test_parse_verdict_fallback_digit():
    from scripts.eval_agent import _parse_verdict

    assert _parse_verdict("Score: 3") == {"score": 3, "issues": ["unparsed verdict"]}


def test_parse_verdict_garbage_returns_none():
    from scripts.eval_agent import _parse_verdict

    assert _parse_verdict("no idea") is None


def test_parse_verdict_rejects_out_of_range():
    from scripts.eval_agent import _parse_verdict

    assert _parse_verdict('{"score": 7, "issues": []}') is None


# ── Sampling ─────────────────────────────────────────────────────────────────


def test_sample_turns_pairs_question_and_answer(obs_db, chats_db):
    from scripts.eval_agent import sample_turns

    _seed_turn(obs_db)
    samples = sample_turns(days=30, limit=10)

    assert len(samples) == 1
    s = samples[0]
    assert "refugees" in s["question"]
    assert "1,200" in s["answer"]
    assert s["turn_id"] == "t1"
    assert s["model_id"] == "google/gemini-3.8-flash"


def test_sample_turns_respects_window_limit(obs_db, chats_db):
    from scripts.eval_agent import sample_turns

    _seed_turn(obs_db, days_old=40)
    assert sample_turns(days=30, limit=10) == []


def test_sample_turns_skips_when_messages_missing(obs_db, tmp_path, monkeypatch):
    import config
    from scripts.eval_agent import sample_turns

    # no chats.db at all
    monkeypatch.setattr(config, "CHATS_DB_PATH", tmp_path / "missing.db", raising=False)
    _seed_turn(obs_db)
    assert sample_turns(days=30, limit=10) == []


# ── Runner (judge monkeypatched) ─────────────────────────────────────────────


def test_run_dry_run_persists_nothing(obs_db, chats_db, monkeypatch):
    import scripts.eval_agent as ev

    _seed_turn(obs_db)
    monkeypatch.setattr(ev, "ask_judge", lambda s, m, **kw: {"score": 4, "issues": ["minor gap"]})

    report = ev.run(days=30, limit=10, apply=False, judge_model="judge/x")
    assert report["scored"] == 1 and report["avg"] == 4.0 and report["dry_run"] is True
    assert obs_db.eval_summary(days=30)["count"] == 0  # dry run: nothing written


def test_run_apply_persists_and_summarizes(obs_db, chats_db, monkeypatch):
    import scripts.eval_agent as ev

    _seed_turn(obs_db, turn_id="t1")  # most recent → sampled first, judged 5
    _seed_turn(obs_db, turn_id="t2", behind_s=10.0)  # sampled second, judged 2
    verdicts = iter([{"score": 5, "issues": []}, {"score": 2, "issues": ["invented figure"]}])
    monkeypatch.setattr(ev, "ask_judge", lambda s, m, **kw: next(verdicts))

    report = ev.run(days=30, limit=10, apply=True, judge_model="judge/x")
    assert report["scored"] == 2
    s = obs_db.eval_summary(days=30)
    assert s["count"] == 2
    assert s["low_count"] == 1
    assert s["distribution"][5] == 1 and s["distribution"][2] == 1
    # low scorers are surfaced with their turn ids for review
    assert {r["turn_id"] for r in report["low"]} == {"t2"}


def test_run_counts_judge_failures(obs_db, chats_db, monkeypatch):
    import scripts.eval_agent as ev

    _seed_turn(obs_db)
    monkeypatch.setattr(ev, "ask_judge", lambda s, m, **kw: None)

    report = ev.run(days=30, limit=10, apply=True, judge_model="judge/x")
    assert report["scored"] == 0 and report["failed"] == 1 and report["avg"] is None
    assert obs_db.eval_summary(days=30)["count"] == 0


def test_rubric_embeds_anti_bias_rules():
    from scripts.eval_agent import _RUBRIC

    assert "Length is NOT quality" in _RUBRIC
    assert "not a failure" in _RUBRIC.lower()
    assert '"score"' in _RUBRIC


# ── G-Eval upgrades: upsert, evidence, cross-family guard ───────────────────


def test_apply_twice_updates_instead_of_duplicating(obs_db, chats_db, monkeypatch):
    import scripts.eval_agent as ev

    _seed_turn(obs_db)
    monkeypatch.setattr(ev, "ask_judge", lambda s, m, **kw: {"score": 2, "issues": ["thin"]})
    ev.run(days=30, limit=10, apply=True, judge_model="judge/x")

    monkeypatch.setattr(ev, "ask_judge", lambda s, m, **kw: {"score": 5, "issues": []})
    ev.run(days=30, limit=10, apply=True, judge_model="judge/x")

    summary = obs_db.eval_summary(days=30)
    assert summary["count"] == 1  # unique(turn_id, judge_model, judge)
    assert summary["avg"] == 5.0  # latest verdict wins
    assert summary["low_count"] == 0


def test_sample_turns_attaches_tool_evidence(obs_db, chats_db):
    from scripts.eval_agent import sample_turns

    _seed_turn(obs_db)
    obs_db.record_chat_turn(
        {
            "turn_id": "t1",
            "uid": "u1",
            "chat_id": "c1",
            "status": "ok",
            "started_at": time.time() - 2,
            "finished_at": time.time() - 1,
        },
        tools=[
            {
                "tool": "search_sitreps",
                "group": "ReliefWeb",
                "server": "native",
                "status": "ok",
                "result_chars": 800,
                "result_preview": "Sudan: 1,200 people displaced in Khartoum [report GW-1]",
                "summary": "3 reports",
            }
        ],
    )
    samples = sample_turns(days=30, limit=10)
    assert len(samples) == 1
    assert "1,200 people displaced" in samples[0]["evidence"]


def test_judge_prompt_declares_missing_evidence():
    from scripts.eval_agent import _judge_messages

    msgs = _judge_messages({"question": "q", "answer": "a", "evidence": ""})
    user = msgs[-1]["content"]
    assert "EVIDENCE: none stored" in user
    assert "ANSWER TO EVALUATE" in user


def test_run_warns_on_same_family_judge(obs_db, chats_db, monkeypatch):
    import scripts.eval_agent as ev

    _seed_turn(obs_db)  # model_id google/gemini-3.8-flash
    monkeypatch.setattr(ev, "ask_judge", lambda s, m, **kw: {"score": 4, "issues": []})
    report = ev.run(days=30, limit=10, apply=False, judge_model="google/gemini-3.1-pro-preview")
    assert report["same_family_warnings"] == ["t1"]
