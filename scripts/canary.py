#!/usr/bin/env python3
"""scripts/canary.py — synthetic uptime/health canary.

Checks the public surface every N minutes (cron) and records failures as
`kind=canary` in errors.db. On failure it can send the same webhook/Telegram
alert used by scripts/alert_check.py.

Checks by default:
- GET /api/health      → 200 and status == ok
- GET /api/public/stats→ 200
- GET /crisis          → 200
Optional: --check-map (only useful when the map cache is warm; cold build is slow).

Usage:
    python scripts/canary.py --base-url http://127.0.0.1:5001
    python scripts/canary.py --base-url https://sightlinehumanitarian.com --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from observability import error_tracking  # noqa: E402


def _check(base_url: str, path: str, timeout: float, expect_status: int = 200) -> dict:
    started = time.perf_counter()
    try:
        resp = requests.get(base_url.rstrip("/") + path, timeout=timeout)
        elapsed = int((time.perf_counter() - started) * 1000)
        body = None
        if path == "/api/health":
            try:
                body = resp.json()
            except ValueError:
                body = None
        ok = resp.status_code == expect_status
        if ok and path == "/api/health" and body and body.get("status") != "ok":
            ok = False
        return {
            "path": path,
            "ok": ok,
            "status": resp.status_code,
            "ms": elapsed,
            "release": (body or {}).get("release", ""),
            "health_status": (body or {}).get("status", ""),
        }
    except Exception as exc:
        return {
            "path": path,
            "ok": False,
            "status": 0,
            "ms": int((time.perf_counter() - started) * 1000),
            "error": str(exc)[:300],
        }


def run(base_url: str, timeout: float = 10.0, check_map: bool = False, alert: bool = True) -> dict:
    paths = ["/api/health", "/api/public/stats", "/crisis"]
    if check_map:
        paths.append("/api/map/countries")
    checks = [_check(base_url, path, timeout) for path in paths]
    failures = [c for c in checks if not c["ok"]]
    for failure in failures:
        error_tracking.record_error(
            kind="canary",
            route=failure["path"],
            method="GET",
            status=failure.get("status", 0),
            exc_type="CanaryFailure",
            message=failure.get("error") or f"HTTP {failure.get('status')}",
            context={"base_url": base_url, "health_status": failure.get("health_status", "")},
        )
    report = {"base_url": base_url, "checks": checks, "ok": not failures, "failures": len(failures)}
    if failures and alert:
        try:
            from scripts.alert_check import send_message

            text = "Sightline canary FAILED:\n" + "\n".join(
                f"- {f['path']} HTTP {f.get('status')} ({f.get('ms')}ms) {f.get('error', '')}" for f in failures
            )
            report["delivery"] = send_message(text, dry_run=False)
        except Exception as exc:
            report["delivery"] = {"error": str(exc)[:200]}
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Synthetic canary for Sightline public surface")
    ap.add_argument("--base-url", default="http://127.0.0.1:5001")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--check-map", action="store_true", help="also check /api/map/countries (needs warm cache)")
    ap.add_argument("--no-alert", action="store_true", help="record failures but do not send webhook")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = run(args.base_url, timeout=args.timeout, check_map=args.check_map, alert=not args.no_alert)
    print(json.dumps(report, ensure_ascii=False) if args.json else json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
