#!/usr/bin/env python3
"""
daily_content_enrichment.py — Daily ACAPS-style digest generation.

Runs inside the daily_scheduler.sh lock block, after ingest (+ visual
pipeline) succeed. For the top N crisis countries it fetches the last
week of chunks from SQLite (never ChromaDB queries — ARM64 segfault),
samples the first chunk per report, and asks Gemini Flash to synthesize
a structured 150-300 word digest. Output lives ONLY in
output/daily_digests/{coverage_date}/{Safe_Country}.json — it never
mutates country_summaries/*.json (another cron full-overwrites those).

Failure posture (D2): per-country LLM failures are caught, logged, and
the country is omitted. The script itself is wrapped '|| true' in the
scheduler; a status file records what happened for /api/health.

Usage:
    python scripts/daily_content_enrichment.py                 # coverage = yesterday
    python scripts/daily_content_enrichment.py --date 2026-09-16
    python scripts/daily_content_enrichment.py --top 10 --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Suppress ONNX/TensorRT noise (never loads here, but keep logs clean)
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("daily_enrichment")

# ── Constants ──────────────────────────────────────────────────────────────
TOP_N = 10  # countries per run (D3 sizing)
CHUNK_WINDOW_DAYS = 7  # look-back window for chunks
CHUNKS_PER_COUNTRY = 50  # upper bound fetched, sampled down
MAX_SAMPLED_REPORTS = 20  # distinct reports in the prompt
PROMPT_CHUNK_CHARS = 500  # per-chunk text excerpt
MAX_TOKENS = 800  # D9: thinking model budget headroom
TEMPERATURE = 0.3
MODEL = "google/gemini-2.5-flash"  # EXPLICIT per-job model (config default is gemma-4-31b-it)
PSEUDO_COUNTRIES = {"world", "global", "multiple countries", "not specified"}

_SYSTEM_PROMPT = """You are a humanitarian analyst writing a daily country digest for Sightline, \
a humanitarian intelligence platform. Style: ACAPS CrisisInSight — short, structured, factual.

Rules:
- Synthesize ONLY from the provided report excerpts and HDX figures. Never speculate.
- Never invent numbers. Every figure must come from the provided HDX data.
- Information gaps must be stated explicitly when the excerpts do not cover something.
- Attribute to trusted sources in general terms (never invent organization names).
- Output ONLY a JSON object with exactly these string fields:
  {"headline": one-line summary, "key_developments": 2-3 sentences,
   "key_concerns": 1-2 sentences, "humanitarian_impact": 1-2 sentences,
   "information_gaps": 1 sentence or "Not yet covered in recent reporting"}
- Total length 150-300 words. No markdown fences in your output."""


def _strip_code_fences(text: str) -> str:
    """Strip ```json / ``` fences (same pattern as weekly_bulletin.py:417-424)."""
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


def _select_countries(top_n: int) -> list[str]:
    """Top-N countries by report mention count, pseudo-countries filtered (D11)."""
    from sitrep.chroma_adapter import ChromaAdapter

    adapter = ChromaAdapter()
    rows = adapter.list_countries_with_counts()
    selected = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name or _is_pseudo_country(name):
            continue
        selected.append(name)
        if len(selected) >= top_n:
            break
    return selected


def _sample_chunks(adapter, country: str, coverage_from: str, coverage_to: str) -> list[dict]:
    """First chunk (executive summary) per report, most recent first (D11).

    get_chunks_by_country_and_themes() orders by report date DESC then
    chunk_index ASC, so the first chunk encountered per report_id is that
    report's opening chunk. Deterministic and reproducible for eval.
    """
    chunks = adapter.get_chunks_by_country_and_themes(
        country, date_from=coverage_from, date_to=coverage_to, limit=CHUNKS_PER_COUNTRY
    )
    sampled: list[dict] = []
    seen_reports: set[object] = set()
    for chunk in chunks:
        report_id = chunk.get("report_id")
        if report_id in seen_reports:
            continue
        seen_reports.add(report_id)
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
    """HDX figures text from the existing country summary (numbers never from the LLM)."""
    from sitrep.country_summary import get_country_summary

    summary = get_country_summary(country)
    if not summary:
        return ""
    text = summary.get("hdx_context_text") or ""
    return str(text).strip()


def _build_user_prompt(country: str, coverage_from: str, coverage_to: str, chunks: list[dict], hdx_text: str) -> str:
    lines = [f"Country: {country}", f"Coverage period: {coverage_from} to {coverage_to}", ""]
    lines.append("Recent report excerpts (trusted humanitarian sources):")
    for chunk in chunks:
        title = (chunk.get("title") or "Untitled").strip()
        chunk_date = (chunk.get("date") or "")[:10]
        themes = (chunk.get("themes") or "").strip()
        text = (chunk.get("text") or "").replace("\n", " ").strip()
        line = f"- [{chunk_date}] {title}"
        if themes:
            line += f" ({themes})"
        if text:
            line += f": {text}"
        lines.append(line)
    lines.append("")
    if hdx_text:
        lines.append("Quantitative HDX figures (use these numbers, do not invent others):")
        lines.append(hdx_text)
    lines.append("")
    lines.append("Write the structured digest JSON now.")
    return "\n".join(lines)


def _synthesize(country: str, prompt: str) -> dict:
    from sitrep.llm_client import chat_simple

    response = chat_simple(
        user_prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        model=MODEL,
    )
    cleaned = _strip_code_fences(response)
    import json as _json

    result = _json.loads(cleaned)
    if not isinstance(result, dict):
        raise ValueError("LLM returned non-object JSON")
    for field in ("headline", "key_developments", "key_concerns", "humanitarian_impact", "information_gaps"):
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"LLM output missing or non-string field: {field}")
    return {
        field: result[field].strip()
        for field in ("headline", "key_developments", "key_concerns", "humanitarian_impact", "information_gaps")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily content enrichment (ACAPS-style digests)")
    parser.add_argument("--date", help="Coverage date (YYYY-MM-DD). Default: yesterday UTC.")
    parser.add_argument("--top", type=int, default=TOP_N, help="Number of countries")
    parser.add_argument("--dry-run", action="store_true", help="Select + fetch, no LLM, no writes")
    args = parser.parse_args()

    coverage_date = args.date or (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    coverage_from = (date.fromisoformat(coverage_date) - timedelta(days=7)).isoformat()

    log.info("=" * 60)
    log.info("Daily content enrichment: coverage %s → %s", coverage_from, coverage_date)
    log.info("=" * 60)

    # Gate: a failed ingest day must not produce digests (only the ingest
    # gate is real — the visual pipeline step is unobservable by design).
    if not _ingest_succeeded_recently():
        log.warning("No recent ingest success marker; skipping enrichment (D8 gate).")
        return 0

    from sitrep.chroma_adapter import ChromaAdapter

    adapter = ChromaAdapter()
    countries = _select_countries(args.top)
    log.info("Selected countries: %s", ", ".join(countries) or "(none)")

    published: list[str] = []
    failures: list[dict] = []

    for country in countries:
        chunks = _sample_chunks(adapter, country, coverage_from, coverage_date)
        if not chunks:
            log.info("%s: 0 chunks in window — skipped (P5: no report = no digest)", country)
            continue
        if args.dry_run:
            log.info("%s: would synthesize from %d chunks (dry-run)", country, len(chunks))
            continue

        hdx_text = _load_hdx_context(country)
        prompt = _build_user_prompt(country, coverage_from, coverage_date, chunks, hdx_text)
        try:
            digest = _synthesize(country, prompt)
        except Exception as exc:  # RuntimeError (retries) or JSON/schema errors
            log.warning("%s: LLM synthesis failed — omitting (%s)", country, exc)
            failures.append({"country": country, "error": str(exc)[:200]})
            continue

        from sitrep.daily_digest import write_digest_atomic

        write_digest_atomic(country, coverage_date, digest, validate=True)
        published.append(country)
        log.info("%s: digest written (%d words approx)", country, sum(len(v.split()) for v in digest.values()))

    status = {
        "date": coverage_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "countries_selected": len(countries),
        "countries_published": len(published),
        "published": published,
        "failures": failures,
    }
    if not args.dry_run:
        from sitrep.daily_digest import write_status_atomic

        write_status_atomic(status)
    log.info("Done: %d published, %d failed, coverage %s", len(published), len(failures), coverage_date)
    return 0


def _ingest_succeeded_recently() -> bool:
    """Heuristic gate: ingest log shows success for yesterday within 26h."""
    log_path = Path("/var/log/sightline/daily_ingest.log")
    if not log_path.exists():
        return True  # dev environment — never block on missing prod log
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")[-4000:]
    except OSError:
        return True
    return "Ingest complete" in text or "ingested" in text.lower()


if __name__ == "__main__":
    sys.exit(main())
