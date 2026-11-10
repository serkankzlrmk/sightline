#!/usr/bin/env python3
"""Build a retrieval golden-set draft with real candidate reports.

This does NOT label relevance. It retrieves real reports with the production
pool-based path and writes a draft entry per question; a human must mark which
candidate report ids are genuinely relevant before running eval_retrieval.

Usage:
    python scripts/build_golden_candidates.py --limit 12 --k 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_SITREP = ROOT / "sitrep"
if str(_SITREP) not in sys.path:
    sys.path.insert(0, str(_SITREP))

from reliefweb_api.country_codes import ISO_TO_COUNTRY  # noqa: E402
from scripts.eval_retrieval import curate  # noqa: E402

RETRIEVAL_SOURCES = {"ReliefWeb", "HDX"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate golden-set candidates for human labeling")
    ap.add_argument("--questions", default=str(ROOT / "scripts" / "eval_questions.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "eval" / "golden_set_draft.json"))
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    questions = [q for q in questions if RETRIEVAL_SOURCES.intersection(q.get("expected_sources", []))]
    if args.limit:
        questions = questions[: args.limit]

    draft = []
    for i, q in enumerate(questions, 1):
        country = ISO_TO_COUNTRY.get(str(q.get("country", "")).upper(), "")
        if not country:
            print(f"[{i}/{len(questions)}] skip {q['id']}: no country mapping")
            continue
        print(f"[{i}/{len(questions)}] {q['id']} ({country})", flush=True)
        try:
            candidates = curate(q["question"], country, k=args.k, use_llm_subqueries=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  failed: {type(exc).__name__}: {exc}")
            continue
        draft.append(
            {
                "query": q["question"],
                "country": country,
                "relevant": [],
                "candidates": candidates,
                "_instruction": "Keep only genuinely relevant report_ids in 'relevant'; delete candidates before evaluating.",
            }
        )
        print(f"  {len(candidates)} candidates")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out} ({len(draft)} queries)")
    print("Human task: set 'relevant' to confirmed report ids, remove candidates/_instruction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
