#!/usr/bin/env python3
"""Seed retrieval golden-set candidates into obs.db for the admin labeling UI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from observability import store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed retrieval candidates from a draft JSON")
    ap.add_argument("--draft", default=str(ROOT / "data" / "eval" / "golden_set_draft.json"))
    ap.add_argument("--questions", default=str(ROOT / "scripts" / "eval_questions.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    by_text = {q["question"]: q["id"] for q in questions}
    rows = []
    for idx, entry in enumerate(draft, 1):
        qid = by_text.get(entry.get("query", ""), f"q{idx}")
        for cand in entry.get("candidates", []):
            rows.append(
                {
                    "query_id": qid,
                    "query": entry.get("query", ""),
                    "country": entry.get("country", ""),
                    "report_id": cand.get("report_id", ""),
                    "title": cand.get("title", ""),
                    "date": cand.get("date", ""),
                    "url": cand.get("url", ""),
                }
            )
    print(f"candidates={len(rows)} queries={len({r['query_id'] for r in rows})}")
    if args.dry_run:
        return 0
    written = store.seed_retrieval_candidates(rows)
    print("written", written, "progress", store.retrieval_progress())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
