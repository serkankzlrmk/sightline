"""Tests for scripts/eval_retrieval.py — IR metrics + production-path scoring.

Pure functions on synthetic ranked lists / a fake adapter. No corpus, no LLM,
no network. Sub-query generation is monkeypatched where needed.
"""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SITREP_DIR = _ROOT / "sitrep"
for _p in (str(_ROOT), str(_SITREP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)  # rag_answers does `import llm_client` (plain)

from sitrep.rag_answers import RETRIEVAL_TOP_K  # noqa: E402

# ── Metric math ──────────────────────────────────────────────────────────────


def test_recall_at_k():
    from scripts.eval_retrieval import recall_at_k

    assert recall_at_k(["a", "b"], {"a"}, 10) == 1.0
    assert recall_at_k(["a"], {"a", "b"}, 10) == 0.5
    assert recall_at_k(["x", "y"], {"a", "b"}, 10) == 0.0
    assert recall_at_k(["a"], set(), 10) == 0.0  # empty gold: no reward
    assert recall_at_k(["x", "b"], {"a", "b"}, k=1) == 0.0
    assert recall_at_k(["x", "b"], {"a", "b"}, k=2) == 0.5


def test_mrr():
    from scripts.eval_retrieval import mrr

    assert mrr(["a"], {"a"}) == 1.0
    assert mrr(["x", "a"], {"a"}) == 0.5
    assert mrr(["x", "y", "a"], {"b"}) == 0.0


def test_ndcg_at_k():
    from scripts.eval_retrieval import ndcg_at_k

    relevant = {"a"}
    assert ndcg_at_k(["a", "x"], relevant, k=10) == pytest.approx(1.0)
    import math

    assert ndcg_at_k(["x", "a"], relevant, k=10) == pytest.approx(1.0 / math.log2(3))
    assert ndcg_at_k(["a", "b", "z"], {"a", "b"}, k=10) == pytest.approx(1.0)
    assert ndcg_at_k(["z", "a"], {"a"}, k=10) < 1.0
    assert ndcg_at_k([], {"a"}, k=10) == 0.0


def test_report_ranking_dedups_chunk_ids():
    from scripts.eval_retrieval import report_ranking

    fused = [
        {"id": "GW-1_0", "text": "t"},
        {"id": "GW-1_1", "text": "t"},
        {"id": "GW-2_0", "text": "t"},
        {"id": "GW-1_2", "text": "t"},
    ]
    assert report_ranking(fused, max_k=10) == ["GW-1", "GW-2"]


# ── Golden set loading ───────────────────────────────────────────────────────


def test_load_gold_valid(tmp_path):
    from scripts.eval_retrieval import load_gold

    p = tmp_path / "gold.json"
    p.write_text(
        json.dumps([{"query": "q", "relevant": ["GW-1"], "country": "Turkiye"}]),
        encoding="utf-8",
    )
    assert load_gold(p) == [{"query": "q", "relevant": ["GW-1"], "country": "Turkiye"}]


@pytest.mark.parametrize(
    "payload",
    [
        '[{"query": ""}]',
        '[{"relevant": []}]',
        '{"query": "q"}',
        "[]",
        '[{"query": "q", "relevant": ["GW-1"]}]',  # missing country → no pool path
    ],
)
def test_load_gold_rejects_bad_labels(tmp_path, payload):
    from scripts.eval_retrieval import load_gold

    p = tmp_path / "gold.json"
    p.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        load_gold(p)


# ── Pipeline-level scoring with a fake adapter ───────────────────────────────


def _fake_adapter(lists_per_call: list[list[str]]):
    """Simplest adapter: ignores the query, returns pre-scripted id lists.

    Tracks every ``candidate_pool`` it receives so a regression test can assert
    the production pool path is actually used (the whole point of the fix).
    """

    class Fake:
        def __init__(self):
            self.calls = iter(lists_per_call)
            self.candidate_pools = []

        def get_chunks_by_country(self, country, limit=2000):
            return [{"id": "POOL_1_0", "text": "pool chunk", "title": "", "url": "", "date": ""}]

        def retrieve(self, query="", country="", k=RETRIEVAL_TOP_K, candidate_pool=None):
            self.candidate_pools.append(candidate_pool)
            ids = next(self.calls)
            return [{"id": cid, "text": "chunk"} for cid in ids]

    return Fake()


def _no_subqueries(monkeypatch):
    """Force deterministic sub-query generation (no LLM, no network)."""
    import scripts.eval_retrieval as ev

    monkeypatch.setattr(ev, "_generate_subqueries", lambda q, n=3: [q])
    return ev


def test_evaluate_query_no_subquery_llm(tmp_path, monkeypatch):
    ev = _no_subqueries(monkeypatch)
    adapter = _fake_adapter([["GW-5_0", "GW-9_0"]])
    out = ev.evaluate_query(adapter, "How many people were affected?", ["GW-5"], "X", k=10)
    assert out["recall_at_k"] == 1.0
    assert out["recall_at_k_stage1"] == 1.0
    assert out["mrr"] == 1.0
    assert out["ndcg_at_k"] == 1.0
    assert out["ranked_reports"][0] == "GW-5"

    # Regression: the production ChromaDB path requires candidate_pool; without it
    # retrieve() returns [] and every metric is silently 0.
    assert adapter.candidate_pools
    assert all(p is not None and len(p) > 0 for p in adapter.candidate_pools)


def test_evaluate_query_requires_country_for_pool(monkeypatch):
    ev = _no_subqueries(monkeypatch)
    adapter = _fake_adapter([["A_0"]])
    with pytest.raises(ValueError):
        ev.evaluate_query(adapter, "q", ["A"], "")


def test_evaluate_query_rrf_promotes_multi_list_overlap():
    from scripts.eval_retrieval import mrr as _mrr
    from scripts.eval_retrieval import report_ranking
    from sitrep.rag_answers import _reciprocal_rank_fusion

    merged = _reciprocal_rank_fusion(
        [
            [{"id": i, "text": "t"} for i in ["A_0", "B_0", "T_0", "C_0"]],
            [{"id": i, "text": "t"} for i in ["D_0", "T_0", "E_0"]],
        ]
    )
    ranked = report_ranking(merged, max_k=10)
    assert ranked[0] == "T"
    assert _mrr(ranked, {"T"}) == 1.0


def test_evaluate_query_miss(monkeypatch):
    ev = _no_subqueries(monkeypatch)
    adapter = _fake_adapter([["A_0"], ["B_0"]])
    out = ev.evaluate_query(adapter, "q", ["GW-9"], "X", k=10)
    assert out["recall_at_k"] == 0.0
    assert out["recall_at_k_stage1"] == 0.0
    assert out["mrr"] == 0.0
    assert out["ndcg_at_k"] == 0.0


def test_aggregate_includes_stage1_ceiling():
    from scripts.eval_retrieval import aggregate

    agg = aggregate(
        [
            {"recall_at_k": 1.0, "recall_at_k_stage1": 1.0, "mrr": 1.0, "ndcg_at_k": 0.9},
            {"recall_at_k": 0.0, "recall_at_k_stage1": 0.5, "mrr": 0.0, "ndcg_at_k": 0.0},
        ]
    )
    assert agg["queries"] == 2
    assert agg["mean_recall_at_k"] == 0.5
    assert agg["mean_recall_at_stage1"] == 0.75
    assert agg["mean_mrr"] == 0.5
    assert agg["mean_ndcg_at_k"] == 0.45


def test_curate_dedups_chunks_into_report_candidates(monkeypatch):
    import scripts.eval_retrieval as ev

    monkeypatch.setattr(ev, "_generate_subqueries", lambda q, n=3: [q])
    monkeypatch.setattr(ev, "_build_adapter", lambda: _fake_adapter([["GW-7_0", "GW-7_1", "GW-3_0"]]))

    candidates = ev.curate("any", country="X", k=10)
    assert [c["report_id"] for c in candidates] == ["GW-7", "GW-3"]
    assert all({"report_id", "title", "date", "url"} == set(c) for c in candidates)


def test_curate_respects_k(monkeypatch):
    import scripts.eval_retrieval as ev

    monkeypatch.setattr(ev, "_generate_subqueries", lambda q, n=3: [q])
    monkeypatch.setattr(ev, "_build_adapter", lambda: _fake_adapter([[f"GW-{i}_0" for i in range(20)]]))

    assert len(ev.curate("any", country="X", k=5)) == 5
