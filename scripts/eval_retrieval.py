#!/usr/bin/env python3
"""scripts/eval_retrieval.py — golden-set retrieval quality metrics (production path).

Computes two-stage metrics over a labeled golden set using the SAME retrieval
path as production (``sitrep/rag_answers.py``): sub-query generation → pool-based
candidate retrieval → Reciprocal Rank Fusion.

Why two stages (NotebookLM research, ``docs/research/notebooklm_rag_eval.md``):
- **Stage 1 (candidate coverage)** sets the ceiling: if the relevant report is not
  in the retrieved candidates, no downstream step can recover it. We report
  Recall@stage1_k (default 50).
- **Stage 2 (what the generator sees)** is the fused top-k cut (default 10):
  nDCG@k and MRR@k measure whether the *right* evidence lands high enough.

IMPORTANT: the ChromaDB backend deliberately returns [] for whole-collection
retrieval without a ``candidate_pool`` (ARM64 segfault guard), so this harness
builds the country pool explicitly and passes it. Without that the harness would
silently score 0 for every query.

Golden set format (JSON list — labels are ReliefWeb report ids, chunk ids are
``{report_id}_{chunk_index}``)::

    [{"query": "...", "relevant": ["GW-2026-0001"], "country": "Turkiye"}, ...]

Usage:
    python scripts/eval_retrieval.py --gold data/golden_set.json --k 10 --stage1-k 50
    python scripts/eval_retrieval.py --gold data/golden_set.json --apply   # persist run
    python scripts/eval_retrieval.py --curate "cholera Yemen" --country Yemen

Offline contract (CI): with no local corpus the run exits non-zero with a clear
message instead of fabricating numbers. Metric math is pure and unit-tested.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_SITREP_DIR = ROOT / "sitrep"
if str(_SITREP_DIR) not in sys.path:
    sys.path.insert(0, str(_SITREP_DIR))  # rag_answers does `import llm_client` (plain)

from observability import store  # noqa: E402
from sitrep.rag_answers import (  # noqa: E402
    RETRIEVAL_TOP_K,
    RRF_K,
    _generate_subqueries,
    _reciprocal_rank_fusion,
)

# ── IR metrics (report-level, binary relevance) ──────────────────────────────


def report_id_of(chunk_id: str) -> str:
    """ReliefWeb chunk ids are ``{report_id}_{chunk_index}`` → report id."""
    return str(chunk_id).rsplit("_", 1)[0]


def report_ranking(fused_chunks: list[dict], max_k: int) -> list[str]:
    """Fused chunks → deduplicated report-id ranking (first appearance wins)."""
    seen: list[str] = []
    for c in fused_chunks[: max_k * 4]:  # look deep enough to fill the dedup window
        rid = report_id_of(c.get("id") or c.get("text", "")[:50])
        if rid not in seen:
            seen.append(rid)
        if len(seen) >= max_k * 3:
            break
    return seen[: max_k * 3]


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Fraction of relevant reports present anywhere in the top-k."""
    if not relevant:
        return 0.0
    hits = len(set(ranked[:k]) & relevant)
    return hits / len(relevant)


def mrr(ranked: list[str], relevant: set[str]) -> float:
    """Mean reciprocal rank of the first relevant report in the ranking."""
    for i, rid in enumerate(ranked, start=1):
        if rid in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    """Binary-gain NDCG@k (rank positions are 1-indexed, discount 1/log2(rank+1))."""
    if not relevant:
        return 0.0
    dcg = sum(1.0 / _discount(i) for i, rid in enumerate(ranked[:k]) if rid in relevant)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / _discount(i) for i in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def _discount(i: int) -> float:
    import math

    return math.log2(i + 2)  # i=0 → rank 1 → log2(2)=1 → discount 1.0


# ── Pool building (the ChromaDB-safe production path) ────────────────────────


def build_pool(adapter, country: str, limit: int = 2000) -> list[dict]:
    """Build the candidate pool exactly like the SITREP pipeline does.

    ``retrieve()`` without ``candidate_pool`` is disabled on the ChromaDB backend
    (ARM64 guard) and returns []. The golden set therefore requires a country so
    the pool can be read from SQLite-backed chunks.
    """
    if not country:
        raise ValueError(
            "golden-set entries need a 'country': the pool-based retrieval path "
            "(used in production) cannot be evaluated without one"
        )
    return adapter.get_chunks_by_country(country, limit=max(1, int(limit)))


# ── Evaluating one gold query against the production pipeline ────────────────


def evaluate_query(
    adapter,
    question: str,
    relevant: list[str],
    country: str,
    k: int = 10,
    stage1_k: int = 50,
    pool: list[dict] | None = None,
    use_llm_subqueries: bool = True,
) -> dict:
    """Run the exact production retrieval path and score stage 1 + stage 2."""
    if pool is None:
        pool = build_pool(adapter, country)
    subqueries = _generate_subqueries(question) if use_llm_subqueries else [question]
    ranked_lists: list[list[dict]] = [
        adapter.retrieve(query=sq, country=country, k=stage1_k, candidate_pool=pool) for sq in subqueries
    ]
    fused = _reciprocal_rank_fusion(ranked_lists, k=RRF_K)
    stage1_ranked = report_ranking(fused, max_k=stage1_k)
    stage2_ranked = stage1_ranked[:k]
    relevant_set = set(relevant)
    return {
        "query": question,
        "country": country,
        "recall_at_k": recall_at_k(stage2_ranked, relevant_set, k),
        "recall_at_k_stage1": recall_at_k(stage1_ranked, relevant_set, stage1_k),
        "mrr": mrr(stage2_ranked, relevant_set),
        "ndcg_at_k": ndcg_at_k(stage2_ranked, relevant_set, k),
        "ranked_reports": stage2_ranked,
        "stage1_reports": stage1_ranked,
    }


def aggregate(per_query: list[dict]) -> dict:
    n = len(per_query)
    if not n:
        return {"queries": 0}
    return {
        "queries": n,
        "mean_recall_at_k": round(sum(q["recall_at_k"] for q in per_query) / n, 4),
        "mean_recall_at_stage1": round(sum(q["recall_at_k_stage1"] for q in per_query) / n, 4),
        "mean_mrr": round(sum(q["mrr"] for q in per_query) / n, 4),
        "mean_ndcg_at_k": round(sum(q["ndcg_at_k"] for q in per_query) / n, 4),
    }


def load_gold(path: str | Path) -> list[dict]:
    """Load + validate the golden set; malformed entries are fatal (labels must be real)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Golden set must be a JSON list")
    if not data:
        raise ValueError("Golden set is empty — nothing to evaluate")
    cleaned = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or not entry.get("query") or not entry.get("relevant"):
            raise ValueError(f"Golden set entry #{i} needs 'query' and 'relevant' (report ids)")
        relevant = [str(r) for r in entry["relevant"]]
        if not relevant:
            raise ValueError(f"Golden set entry #{i} has empty 'relevant'")
        country = str(entry.get("country", "")).strip()
        if not country:
            raise ValueError(f"Golden set entry #{i} needs a 'country' (pool-based retrieval)")
        cleaned.append({"query": str(entry["query"]), "relevant": relevant, "country": country})
    return cleaned


# ── Runner ───────────────────────────────────────────────────────────────────


def run(
    gold_path: str,
    k: int = 10,
    stage1_k: int = 50,
    limit: int | None = None,
    use_llm_subqueries: bool = True,
    apply: bool = False,
) -> dict:
    """Load the golden set, score each query, aggregate (and optionally persist)."""
    gold = load_gold(gold_path)
    if limit:
        gold = gold[:limit]
    adapter = _build_adapter()
    pools: dict[str, list[dict]] = {}
    per_query: list[dict] = []
    for g in gold:
        country = g["country"]
        if country not in pools:
            pools[country] = build_pool(adapter, country)
        per_query.append(
            evaluate_query(
                adapter,
                g["query"],
                g["relevant"],
                country,
                k=k,
                stage1_k=stage1_k,
                pool=pools[country],
                use_llm_subqueries=use_llm_subqueries,
            )
        )
    result = {
        "k": k,
        "stage1_k": stage1_k,
        "gold_path": str(gold_path),
        "per_query": per_query,
        "aggregate": aggregate(per_query),
        "applied": False,
    }
    if apply:
        result["applied"] = store.record_retrieval_eval(gold_path=str(gold_path), k=k, result=result, stage1_k=stage1_k)
    return result


def _build_adapter():
    """Resolve the real ChromaAdapter; fail loudly when there is no local corpus."""
    try:
        from blueprints.helpers import get_chroma_adapter

        adapter = get_chroma_adapter()
        if adapter is not None:
            return adapter
    except Exception:
        pass
    raise SystemExit(
        "no local corpus available (ChromaDB adapter unreachable) — "
        "run this on a machine with the reliefweb.db/chroma data, not in CI"
    )


def curate(query: str, country: str, k: int = 10, use_llm_subqueries: bool = True) -> list[dict]:
    """Candidate generation for human labeling: retrieve + print real reports.

    The caller marks which candidates are genuinely relevant; only those ids go
    into the golden set. Labels must come from a human — never auto-fill the
    ranking into 'relevant'.
    """
    adapter = _build_adapter()
    pool = build_pool(adapter, country)
    subqueries = _generate_subqueries(query) if use_llm_subqueries else [query]
    ranked_lists: list[list[dict]] = [
        adapter.retrieve(query=sq, country=country, k=max(RETRIEVAL_TOP_K, k), candidate_pool=pool) for sq in subqueries
    ]
    fused = _reciprocal_rank_fusion(ranked_lists, k=RRF_K)
    seen: list[dict] = []
    seen_ids: set[str] = set()
    for chunk in fused[: k * 4]:
        rid = report_id_of(chunk.get("id") or "")
        if rid in seen_ids:
            continue
        seen_ids.add(rid)
        seen.append(
            {
                "report_id": rid,
                "title": (chunk.get("title") or "")[:110],
                "date": chunk.get("date", ""),
                "url": chunk.get("url", ""),
            }
        )
        if len(seen) >= k:
            break
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description="Golden-set retrieval metrics (Recall@K / MRR / nDCG@10)")
    ap.add_argument("--gold", help="path to golden set JSON")
    ap.add_argument("--k", type=int, default=10, help="stage-2 cut (what the generator sees)")
    ap.add_argument("--stage1-k", type=int, default=50, help="candidate coverage cut (ceiling)")
    ap.add_argument("--limit", type=int, default=None, help="evaluate only the first N queries")
    ap.add_argument("--apply", action="store_true", help="persist the run into obs.db eval_retrieval")
    ap.add_argument("--single-query", action="store_true", help="skip LLM sub-query generation (cheaper)")
    ap.add_argument(
        "--curate",
        metavar="QUERY",
        help="labeling helper: print the top-K real reports a query retrieves (human picks 'relevant')",
    )
    ap.add_argument("--country", default="", help="country filter for --curate")
    args = ap.parse_args()

    if args.curate:
        candidates = curate(args.curate, args.country, k=args.k, use_llm_subqueries=not args.single_query)
        print(
            json.dumps(
                {"query": args.curate, "country": args.country, "candidates": candidates}, ensure_ascii=False, indent=2
            )
        )
        print("\n# copy the genuinely relevant report_ids into a golden set entry:")
        print('# {"query": ..., "relevant": ["..."], "country": ...}')
        return 0

    if not args.gold:
        ap.error("--gold is required unless --curate is used")
    report = run(
        args.gold,
        k=args.k,
        stage1_k=args.stage1_k,
        limit=args.limit,
        use_llm_subqueries=not args.single_query,
        apply=args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
