#!/usr/bin/env python3
"""scripts/alert_check.py — threshold-based alerts for Sightline.

Designed for cron (every 5 minutes), not an in-process thread: survives gunicorn
restarts and never blocks a request.

Checks:
- 5xx rate over a short window (error_stats_minute)
- tool error rate over the last day (obs.db tool_calls)
- optional /api/health status (pass --health-url)

Sends to ALERT_WEBHOOK_URL (Slack/Discord/generic JSON) and/or Telegram
(ALERT_TELEGRAM_BOT_TOKEN + ALERT_TELEGRAM_CHAT_ID). Cooldowns live in errors.db
(alert_state) so a persistent problem does not spam.

Usage:
    python scripts/alert_check.py                 # check + send (if configured)
    python scripts/alert_check.py --dry-run       # print alerts, no send/cooldown
    python scripts/alert_check.py --test          # send a test message
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import config  # noqa: E402
from observability import error_tracking, store  # noqa: E402


def collect_metrics(minutes: int = 15) -> dict:
    stats = error_tracking.window_stats(minutes=minutes)
    tools = store.tool_stats(days=1)
    calls = sum(int(t.get("calls") or 0) for t in tools)
    errors = sum(int(t.get("errors") or 0) for t in tools)
    cost = store.daily_cost_summary(days=1)
    return {
        "window_minutes": stats["window_minutes"],
        "requests": stats["requests"],
        "errors": stats["errors"],
        "error_rate": stats["error_rate"],
        "tool_calls": calls,
        "tool_errors": errors,
        "tool_error_rate": round(errors / calls, 4) if calls else 0.0,
        "daily_cost": cost["cost"],
        "top_user_cost": (cost.get("top_user") or {}).get("cost", 0.0),
        "top_user_uid": (cost.get("top_user") or {}).get("uid", ""),
    }


def check_health(url: str, timeout: int = 5) -> dict:
    if not url:
        return {"checked": False}
    try:
        resp = requests.get(url.rstrip("/") + "/api/health", timeout=timeout)
        payload = {}
        try:
            payload = resp.json()
        except ValueError:
            pass
        return {
            "checked": True,
            "status_code": resp.status_code,
            "status": payload.get("status", ""),
            "release": payload.get("release", ""),
        }
    except Exception as exc:
        return {"checked": True, "status_code": 0, "status": "unreachable", "error": str(exc)[:200]}


def evaluate(
    metrics: dict,
    health: dict,
    min_requests: int,
    error_rate: float,
    tool_rate: float,
    daily_cost_limit: float = 0.0,
    user_cost_limit: float = 0.0,
) -> list[dict]:
    alerts = []
    if metrics["requests"] >= min_requests and metrics["error_rate"] > error_rate:
        alerts.append(
            {
                "key": "5xx_rate",
                "severity": "critical",
                "title": "5xx rate above threshold",
                "detail": f"{metrics['error_rate'] * 100:.1f}% of {metrics['requests']} requests in {metrics.get('window_minutes', 15)}m",
            }
        )
    if metrics["tool_calls"] >= min_requests and metrics["tool_error_rate"] > tool_rate:
        alerts.append(
            {
                "key": "tool_error_rate",
                "severity": "warning",
                "title": "Tool error rate above threshold",
                "detail": f"{metrics['tool_error_rate'] * 100:.1f}% of {metrics['tool_calls']} tool calls (24h)",
            }
        )
    if daily_cost_limit and metrics.get("daily_cost", 0.0) > daily_cost_limit:
        alerts.append(
            {
                "key": "daily_cost",
                "severity": "warning",
                "title": "Daily LLM cost above threshold",
                "detail": f"${metrics.get('daily_cost', 0):.2f} in the last 24h (limit ${daily_cost_limit:.2f})",
            }
        )
    if user_cost_limit and metrics.get("top_user_cost", 0.0) > user_cost_limit:
        alerts.append(
            {
                "key": "user_daily_cost",
                "severity": "warning",
                "title": "Single user cost above threshold",
                "detail": f"${metrics.get('top_user_cost', 0):.2f} by user {metrics.get('top_user_uid', '')[:12]} (limit ${user_cost_limit:.2f})",
            }
        )
    if health.get("checked") and (health.get("status_code") != 200 or health.get("status") != "ok"):
        alerts.append(
            {
                "key": "health_degraded",
                "severity": "critical",
                "title": "Health check degraded",
                "detail": f"HTTP {health.get('status_code')} status={health.get('status') or '—'}",
            }
        )
    return alerts


def format_message(alerts: list[dict]) -> str:
    lines = ["Sightline alert check:"]
    for alert in alerts:
        lines.append(f"[{alert['severity'].upper()}] {alert['title']} — {alert['detail']}")
    return "\n".join(lines)


def send_message(text: str, dry_run: bool = False) -> dict:
    """Send via generic webhook and/or Telegram. Returns delivery status."""
    result = {"webhook": False, "telegram": False, "skipped": False}
    if dry_run:
        result["skipped"] = True
        return result
    if config.ALERT_WEBHOOK_URL:
        try:
            requests.post(config.ALERT_WEBHOOK_URL, json={"text": text}, timeout=10)
            result["webhook"] = True
        except Exception:
            result["webhook"] = False
    if config.ALERT_TELEGRAM_BOT_TOKEN and config.ALERT_TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{config.ALERT_TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": config.ALERT_TELEGRAM_CHAT_ID, "text": text},
                timeout=10,
            )
            result["telegram"] = True
        except Exception:
            result["telegram"] = False
    return result


def run(dry_run: bool = False, test: bool = False, health_url: str = "", minutes: int = 15) -> dict:
    if test:
        text = "Sightline test alert — alerting is configured correctly."
        return {"test": True, "message": text, "delivery": send_message(text, dry_run=dry_run)}
    metrics = collect_metrics(minutes=minutes)
    health = check_health(health_url)
    alerts = evaluate(
        metrics,
        health,
        min_requests=config.ALERT_MIN_REQUESTS,
        error_rate=config.ALERT_5XX_RATE,
        tool_rate=config.ALERT_TOOL_ERROR_RATE,
        daily_cost_limit=config.ALERT_DAILY_COST_USD,
        user_cost_limit=config.ALERT_USER_DAILY_COST_USD,
    )
    fired = []
    for alert in alerts:
        allowed = dry_run or error_tracking.alert_allowed(alert["key"], cooldown_seconds=config.ALERT_COOLDOWN_MIN * 60)
        if allowed:
            fired.append(alert)
    delivery = {"webhook": False, "telegram": False, "skipped": True}
    if fired and not dry_run:
        delivery = send_message(format_message(fired), dry_run=False)
    return {
        "metrics": metrics,
        "health": health,
        "alerts": fired,
        "suppressed": len(alerts) - len(fired),
        "delivery": delivery,
        "dry_run": dry_run,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Sightline threshold alerts (cron-friendly)")
    ap.add_argument("--dry-run", action="store_true", help="print alerts without sending or cooldown")
    ap.add_argument("--test", action="store_true", help="send one test message")
    ap.add_argument("--health-url", default="", help="base URL to probe /api/health (optional)")
    ap.add_argument("--minutes", type=int, default=15, help="5xx window in minutes")
    args = ap.parse_args()
    report = run(dry_run=args.dry_run, test=args.test, health_url=args.health_url, minutes=args.minutes)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
