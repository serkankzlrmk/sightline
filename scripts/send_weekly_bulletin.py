#!/usr/bin/env python3
"""Send the latest weekly bulletin to confirmed subscribers.

Designed for a Monday cron inside the app container:
  0 9 * * 1 docker exec sightline python scripts/send_weekly_bulletin.py
"""
import json
import sys

from growth import newsletter


def main() -> int:
    if not newsletter.configured():
        print(json.dumps({"ok": False, "error": "Brevo is not configured"}))
        return 1
    result = newsletter.send_broadcast("bulletin")
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
