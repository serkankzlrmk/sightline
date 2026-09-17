#!/usr/bin/env python3
"""
generate_deep_dives.py — Weekly deep-dive analyses (Tier C).

Cron: Monday 06:45 UTC (after the 06:30 bulletin). Generates 300-500
word deep dives for the top 3-5 crises of the COVERAGE week (the week
the bulletin covers), stored in output/deep_dives/{coverage_week}/.

Design rules (design doc, D10 reversal approved 2026-09-17):
- Output lives ONLY in output/deep_dives/{coverage_week}/ — no bulletin
  JSON field (the bulletin is written at 06:30, before deep dives run;
  SSR pages read the files directly at render time instead).
- Coverage-week labeling, not run-week: {coverage_week} is the ISO week
  the analysis covers, matching generate_bulletin.py --last-week.
- Model: Flash with higher max_tokens; Pro only if quality visibly lags.
- Real data only (P2): numbers come from HDX context, never invented.

Usage:
    python scripts/generate_deep_dives.py                # last week
    python scripts/generate_deep_dives.py --week 2026-W37
    python scripts/generate_deep_dives.py --dry-run
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("deep_dives")

DEEP_DIVES_DIR = Path(os.getenv("DEEP_DIVES_DIR", "output/deep_dives"))
TOP_N = 5  # crises per week
MAX_TOKENS = 2000  # 300-500 words needs real headroom
TEMPERATURE = 0.3
MODEL = "google/gemini-2.5-flash"
MAX_SAMPLED_REPORTS = 30
PROMPT_CHUNK_CHARS = 500
PSEUDO_COUNTRIES = {"world", "global", "multiple countries", "not specified"}

_SYSTEM_PROMPT = """You are a senior humanitarian analyst writing a weekly deep-dive \
for Sightline, a humanitarian intelligence platform. Style: ACAPS CrisisInSight \
briefing notes — analytical, factual, decision-ready.

Rules:
- Synthesize ONLY from the provided report excerpts and HDX figures. Never speculate.
- Never invent numbers. Figures belong to the interface's HDX figures panel, NOT your prose:
  do not restate dollar amounts or funding percentages inside your text — describe them in words
  (e.g. "funding remains well below requirements") instead of copying raw strings.
- Each field covers DISTINCT ground — do not repeat the same facts across fields:
  headline = the single most important shift of the week;
  what_changed = concrete events and changes from this week's excerpts;
  why_it_matters = consequences for response and the people affected;
  what_to_watch = 2-3 forward-looking observations grounded in the reporting;
  information_gaps = what the excerpts do NOT cover.
- Vary sentence openings; never start every field with the country name.
- State information gaps explicitly.
- Attribute to trusted sources in general terms (never invent organization names).
- Plain sentences only: no markdown, no bullet characters, no em dashes.
- Output ONLY a JSON object with exactly these string fields:
  {"headline": one-line what changed, "what_changed": 2-4 sentences,
   "why_it_matters": 2-3 sentences, "what_to_watch": 2-3 forward-looking
   observations grounded in the reporting, "information_gaps": 1 sentence}
- Total length 300-500 words. No markdown fences in your output."""


def _coverage_week(date_from: str) -> str:
    """ISO week label (e.g. 2026-W37) for a Monday date."""
    d = datetime.fromisoformat(date_from).date()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _last_week_range() -> tuple[str, str]:
    """(Monday, Sunday) of last week, matching generate_bulletin.py --last-week."""
    today = datetime.now(UTC).date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    return last_monday.isoformat(), (last_monday + timedelta(days=6)).isoformat()


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _is_pseudo_country(name: str) -> bool:
    return name.strip().lower() in PSEUDO_COUNTRIES


def _load_bulletin(coverage_week: str) -> dict | None:
    """Load the bulletin for the coverage week (its country list ranks crises)."""
    from sitrep.weekly_bulletin import BULLETINS_DIR, get_bulletin

    path = BULLETINS_DIR / f"{coverage_week}_bulletin.json"
    if not path.exists():
        return None
    return get_bulletin(f"{coverage_week}_bulletin.json")


def _select_countries(bulletin: dict | None, top_n: int) -> list[str]:
    """Top-N crises from the bulletin's country ranking, pseudo-countries filtered."""
    if not bulletin:
        return []
    selected = []
    for crisis in bulletin.get("crises") or []:
        name = str(crisis.get("country") or "").strip()
        if not name or _is_pseudo_country(name):
            continue
        selected.append(name)
        if len(selected) >= top_n:
            break
    return selected


def _sample_chunks(adapter, country: str, coverage_from: str, coverage_to: str) -> list[dict]:
    """First chunk per report across the week, most recent first."""
    chunks = adapter.get_chunks_by_country_and_themes(
        country, date_from=coverage_from, date_to=coverage_to, limit=MAX_SAMPLED_REPORTS * 3
    )
    sampled: list[dict] = []
    seen: set[object] = set()
    for chunk in chunks:
        report_id = chunk.get("report_id")
        if report_id in seen:
            continue
        seen.add(report_id)
        sampled.append(
            {
                "report_id": report_id,
                "title": (chunk.get("title") or "").strip(),
                "date": (chunk.get("date") or "").strip(),
                "themes": (chunk.get("themes") or "").strip(),
                "text": (chunk.get("text") or "")[:PROMPT_CHUNK_CHARS],
            }
        )
        if len(sampled) >= MAX_SAMPLED_REPORTS:
            break
    return sampled


def _load_hdx_context(country: str) -> str:
    from sitrep.country_summary import get_country_summary

    summary = get_country_summary(country)
    if not summary:
        return ""
    return str(summary.get("hdx_context_text") or "").strip()


def _build_user_prompt(country: str, coverage_from: str, coverage_to: str, chunks: list[dict], hdx_text: str) -> str:
    lines = [
        f"Country: {country}",
        f"Week: {coverage_from} to {coverage_to}",
        "",
        "Report excerpts from trusted humanitarian sources this week:",
    ]
    for chunk in chunks:
        line = f"- [{chunk['date'][:10]}] {chunk['title']}"
        if chunk["themes"]:
            line += f" ({chunk['themes']})"
        if chunk["text"]:
            line += f": {chunk['text']}"
        lines.append(line)
    lines.append("")
    if _hdx := (hdx_text or "").strip():
        lines.append("Quantitative HDX figures (use these numbers, do not invent others):")
        lines.append(_hdx)
    lines.append("")
    lines.append("Write the structured deep-dive JSON now.")
    return "\n".join(lines)


def _synthesize(prompt: str) -> dict:
    from sitrep.llm_client import chat_simple

    response = chat_simple(
        user_prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        model=MODEL,
    )
    result = json.loads(_strip_code_fences(response))
    if not isinstance(result, dict):
        raise ValueError("LLM returned non-object JSON")
    fields = ("headline", "what_changed", "why_it_matters", "what_to_watch", "information_gaps")
    cleaned = {}
    for field in fields:
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"LLM output missing or non-string field: {field}")
        cleaned[field] = value.strip()
    return cleaned


def _week_slug(country: str) -> str:
    from sitrep.utils import safe_filename

    return safe_filename(country)


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly deep-dive generation (Tier C)")
    parser.add_argument("--week", help="Coverage week label (e.g. 2026-W37). Default: last week.")
    parser.add_argument("--top", type=int, default=TOP_N, help="Number of crises")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.week and re.fullmatch(r"\d{4}-W\d{2}", args.week):
        coverage_week = args.week
        iso_year, week_num = int(args.week[:4]), int(args.week[6:])
        monday = datetime.fromisocalendar(iso_year, week_num, 1).date()
    else:
        coverage_from, _ = _last_week_range()
        monday = datetime.fromisoformat(coverage_from).date()
        coverage_week = _coverage_week(coverage_from)
    coverage_from = monday.isoformat()
    coverage_to = (monday + timedelta(days=6)).isoformat()

    log.info("=" * 60)
    log.info("Weekly deep dives: coverage %s (%s to %s)", coverage_week, coverage_from, coverage_to)
    log.info("=" * 60)

    bulletin = _load_bulletin(coverage_week)
    countries = _select_countries(bulletin, args.top)
    if not countries:
        log.warning("No countries selected (missing or empty bulletin %s) — nothing to do", coverage_week)
        return 0
    log.info("Selected: %s", ", ".join(countries))

    from sitrep.chroma_adapter import ChromaAdapter

    adapter = ChromaAdapter()
    published: list[str] = []
    failures: list[dict] = []

    for country in countries:
        chunks = _sample_chunks(adapter, country, coverage_from, coverage_to)
        if not chunks:
            log.info("%s: 0 chunks in week — skipped (P5)", country)
            continue
        if args.dry_run:
            log.info("%s: would write deep dive from %d chunks (dry-run)", country, len(chunks))
            continue

        prompt = _build_user_prompt(country, coverage_from, coverage_to, chunks, _load_hdx_context(country))
        try:
            dive = _synthesize(prompt)
        except Exception as exc:
            log.warning("%s: synthesis failed — omitting (%s)", country, exc)
            failures.append({"country": country, "error": str(exc)[:200]})
            continue

        out_dir = DEEP_DIVES_DIR / coverage_week
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{_week_slug(country)}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dive, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        published.append(country)
        log.info("%s: deep dive written", country)

    status = {
        "coverage_week": coverage_week,
        "coverage_from": coverage_from,
        "coverage_to": coverage_to,
        "generated_at": datetime.now(UTC).isoformat(),
        "published": published,
        "failures": failures,
    }
    if not args.dry_run:
        status_path = DEEP_DIVES_DIR / "status.json"
        tmp = status_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, status_path)
    log.info("Done: %d published, %d failed (%s)", len(published), len(failures), coverage_week)
    return 0


if __name__ == "__main__":
    sys.exit(main())
