#!/usr/bin/env python3
"""scripts/load_test.py — lightweight HTTP load test for Sightline.

No external load-test binary: async httpx, fixed request count, percentile
report. Intended for local/staging baselines (public endpoints by default).
For chat SSE load tests, use a mock OpenAI-compatible server so runs cost no
LLM tokens (planned separately).

Examples:
    python scripts/load_test.py --concurrency 20 --requests 200
    python scripts/load_test.py --paths /crisis,/countries --concurrency 50 --requests 500
    python scripts/load_test.py --base-url http://127.0.0.1:5001 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx

DEFAULT_PATHS = ["/api/public/stats", "/api/map/countries", "/crisis"]


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, int(round((p / 100.0) * (len(sorted_values) - 1)))))
    return round(sorted_values[idx], 2)


async def _worker(client: httpx.AsyncClient, base_url: str, paths: list[str], count: int, results: list, errors: list):
    for i in range(count):
        path = paths[i % len(paths)]
        started = time.perf_counter()
        try:
            resp = await client.get(base_url.rstrip("/") + path, timeout=30.0)
            elapsed = (time.perf_counter() - started) * 1000
            results.append(elapsed)
            if resp.status_code >= 400:
                errors.append({"path": path, "status": resp.status_code})
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            results.append(elapsed)
            errors.append({"path": path, "status": 0, "error": str(exc)[:200]})


async def run(base_url: str, paths: list[str], concurrency: int, requests: int) -> dict:
    per_worker = max(1, requests // max(1, concurrency))
    results: list[float] = []
    errors: list[dict] = []
    started = time.perf_counter()
    async with httpx.AsyncClient(follow_redirects=False) as client:
        await asyncio.gather(
            *[_worker(client, base_url, paths, per_worker, results, errors) for _ in range(concurrency)]
        )
    total_seconds = time.perf_counter() - started
    results.sort()
    total = len(results)
    return {
        "base_url": base_url,
        "paths": paths,
        "concurrency": concurrency,
        "requested": requests,
        "total": total,
        "errors": len(errors),
        "error_rate": round(len(errors) / total, 4) if total else 0.0,
        "rps": round(total / total_seconds, 2) if total_seconds else 0.0,
        "p50_ms": percentile(results, 50),
        "p95_ms": percentile(results, 95),
        "p99_ms": percentile(results, 99),
        "max_ms": round(results[-1], 2) if results else 0.0,
        "duration_s": round(total_seconds, 2),
        "error_samples": errors[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Sightline HTTP load test (async httpx)")
    ap.add_argument("--base-url", default="http://127.0.0.1:5001")
    ap.add_argument("--paths", default=",".join(DEFAULT_PATHS), help="comma-separated GET paths")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--json", action="store_true", help="print one-line JSON only")
    args = ap.parse_args()
    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    if not paths:
        print("error: no paths", file=sys.stderr)
        return 2
    report = asyncio.run(run(args.base_url, paths, max(1, args.concurrency), max(1, args.requests)))
    print(json.dumps(report, ensure_ascii=False) if args.json else json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
