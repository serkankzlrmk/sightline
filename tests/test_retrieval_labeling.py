"""Tests for the admin retrieval golden-set labeling flow."""

import pytest


@pytest.fixture()
def obs_env(tmp_path, monkeypatch):
    import config
    from observability import store

    monkeypatch.setattr(config, "OBS_DB_PATH", tmp_path / "obs.db", raising=False)
    monkeypatch.setattr(config, "OBS_ENABLED", True, raising=False)
    yield store


def _rows():
    return [
        {
            "query_id": "q1",
            "query": "cholera Yemen",
            "country": "Yemen",
            "report_id": "r1",
            "title": "A",
            "date": "2026-01-01",
            "url": "https://reliefweb.int/node/1",
        },
        {
            "query_id": "q1",
            "query": "cholera Yemen",
            "country": "Yemen",
            "report_id": "r2",
            "title": "B",
            "date": "2026-01-02",
            "url": "https://reliefweb.int/node/2",
        },
        {
            "query_id": "q2",
            "query": "floods Pakistan",
            "country": "Pakistan",
            "report_id": "r3",
            "title": "C",
            "date": "2026-01-03",
            "url": "https://reliefweb.int/node/3",
        },
    ]


def test_seed_label_queue_and_export(obs_env):
    store = obs_env
    assert store.seed_retrieval_candidates(_rows()) == 3
    p = store.retrieval_progress()
    assert p == {"queries": 2, "labeled_queries": 0, "candidates": 3, "labeled_candidates": 0, "relevant": 0}

    q = store.retrieval_next_query()
    assert q["query_id"] == "q1"
    assert [c["report_id"] for c in q["candidates"]] == ["r1", "r2"]

    assert store.save_retrieval_labels("q1", ["r2"], rater="tester") == 1
    p = store.retrieval_progress()
    assert p["labeled_queries"] == 1
    assert p["labeled_candidates"] == 2
    assert p["relevant"] == 1
    assert store.retrieval_golden_set() == [{"query": "cholera Yemen", "relevant": ["r2"], "country": "Yemen"}]

    # Remaining query is q2, with no relevant reports; export excludes it.
    assert store.retrieval_next_query()["query_id"] == "q2"


def test_api_queue_label_export(obs_env):
    store = obs_env
    store.seed_retrieval_candidates(_rows())
    import server

    client = server.app.test_client()
    r = client.get("/api/admin/obs/retrieval/queue")
    assert r.status_code == 200
    assert r.get_json()["query"]["query_id"] == "q1"

    r = client.post(
        "/api/admin/obs/retrieval/label",
        json={"query_id": "q1", "relevant": ["r1"]},
    )
    assert r.status_code == 200
    assert r.get_json()["progress"]["relevant"] == 1

    r = client.get("/api/admin/obs/retrieval/export")
    assert r.status_code == 200
    assert r.get_json()["golden_set"][0]["relevant"] == ["r1"]
