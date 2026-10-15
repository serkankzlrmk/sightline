#!/usr/bin/env python3
"""Submit sitemap URLs to IndexNow (Bing, Seznam, Yandex...).

Reads SITE_URL/sitemap.xml and POSTs URLs to the shared IndexNow endpoint
(api.indexnow.org fans out to every participating engine).

Usage:
  python scripts/notify_indexnow.py --days 7   # only URLs with lastmod >= cutoff
  python scripts/notify_indexnow.py --all      # everything in the sitemap

Wired for the daily digest / weekly deep-dive crons: run with --days 2 after
content generation so new pages reach Bing within minutes instead of weeks.
Requires the verification file https://<host>/<INDEXNOW_KEY>.txt (served by
blueprints/seo_bp.py).

Output: English only, per project convention.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

from config import INDEXNOW_KEY, SITE_URL  # noqa: E402

ENDPOINT = "https://api.indexnow.org/IndexNow"
SITEMAP_URL = f"{SITE_URL}/sitemap.xml"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
BATCH_SIZE = 100  # IndexNow soft cap per request
LOCAL_CACHE = "/tmp/indexnow_submitted.json"
MIN_INTERVAL_SECONDS = 600  # avoid hammering the endpoint across cron runs


def fetch_sitemap() -> list[tuple[str, str]]:
    """Return [(url, lastmod or '')] from the live sitemap."""
    with urllib.request.urlopen(SITEMAP_URL, timeout=30) as resp:
        body = resp.read()
    root = ET.fromstring(body)
    out: list[tuple[str, str]] = []
    for loc in root.iter(f"{NS}url"):
        url_el = loc.find(f"{NS}loc")
        mod_el = loc.find(f"{NS}lastmod")
        if url_el is not None and (url_el.text or "").strip():
            url = (url_el.text or "").strip()
            out.append((url, (mod_el.text or "").strip() if mod_el is not None else ""))
    return out

def should_submit(url: str, lastmod: str, days: int | None) -> bool:
    if days is None:
        return True
    if not lastmod:
        return False
    try:
        cutoff = time.time() - days * 86400
        mod_time = time.mktime(time.strptime(lastmod, "%Y-%m-%d"))
        return mod_time >= cutoff
    except ValueError:
        return False


def _throttled_against_cache() -> bool:
    try:
        data = json.loads(open(LOCAL_CACHE).read())
        return time.time() - data.get("ts", 0) < MIN_INTERVAL_SECONDS
    except (OSError, ValueError):
        return False


def _touch_cache() -> None:
    try:
        with open(LOCAL_CACHE, "w") as f:
            json.dump({"ts": time.time()}, f)
    except OSError:
        pass


def submit(urls: list[str]) -> tuple[int, str]:
    payloads_ok = 0
    errors: list[str] = []
    for i in range(0, len(urls), BATCH_SIZE):
        batch = urls[i : i + BATCH_SIZE]
        payload = json.dumps(
            {"host": urllib.parse.urlparse(SITE_URL).netloc, "key": INDEXNOW_KEY, "urlList": batch}
        ).encode()
        req = urllib.request.Request(
            ENDPOINT, data=payload, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                code = resp.status
        except urllib.error.HTTPError as exc:
            errors.append(f"HTTP {exc.code} on batch {i // BATCH_SIZE + 1}")
            continue
        except urllib.error.URLError as exc:
            errors.append(f"network error on batch {i // BATCH_SIZE + 1}: {exc.reason}")
            continue
        if code in (200, 202):
            payloads_ok += len(batch)
        else:
            errors.append(f"HTTP {code} on batch {i // BATCH_SIZE + 1}")
    return payloads_ok, "; ".join(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit sitemap URLs to IndexNow.")
    parser.add_argument("--days", type=int, default=None, help="only URLs with lastmod within N days")
    parser.add_argument("--all", action="store_true", help="submit every sitemap URL")
    parser.add_argument("--force", action="store_true", help="ignore the throttling cache")
    args = parser.parse_args()

    cutoff_days: int | None = None if args.all else (args.days if args.days is not None else 2)

    if not args.force and _throttled_against_cache():
        print("throttled: another submission ran <10 minutes ago; pass --force to override")
        return 0

    try:
        entries = fetch_sitemap()
    except (urllib.error.URLError, ET.ParseError) as exc:
        print(f"failed to fetch sitemap: {exc}")
        return 1

    if not _keyfile_reachable():
        print("warning: key file did not return the key itself; submission may be rejected")

    urls = [u for u, lastmod in entries if should_submit(u, lastmod, cutoff_days)]
    if not urls:
        print("no URLs matched the filter; nothing submitted")
        return 0

    ok, err = submit(urls)
    print(f"submitted {ok}/{len(urls)} URLs")
    if err:
        print(f"warnings: {err}")
        return 1
    _touch_cache()
    return 0


def _keyfile_reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{SITE_URL}/{INDEXNOW_KEY}.txt", timeout=15) as resp:
            return resp.status == 200 and resp.read().decode().strip() == INDEXNOW_KEY
    except (urllib.error.URLError, OSError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
