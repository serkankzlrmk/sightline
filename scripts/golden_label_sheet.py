#!/usr/bin/env python3
"""Export/import a human-friendly CSV labeling sheet for retrieval golden sets.

Export writes one row per (query, candidate report). A human marks the
``relevant`` column with 1/yes/evet/x for genuinely relevant reports. Import
groups confirmed rows back into the golden-set JSON format consumed by
``scripts/eval_retrieval.py``.

Usage:
    python scripts/golden_label_sheet.py --mode export
    python scripts/golden_label_sheet.py --mode import
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUTHY = {"1", "true", "yes", "y", "evet", "x", "relevant", "ilgili"}


def export(draft_path: Path, csv_path: Path) -> int:
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    rows = 0
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["query", "country", "report_id", "date", "title", "url", "relevant"])
        writer.writeheader()
        for entry in draft:
            for cand in entry.get("candidates", []):
                writer.writerow(
                    {
                        "query": entry["query"],
                        "country": entry.get("country", ""),
                        "report_id": cand.get("report_id", ""),
                        "date": (cand.get("date") or "")[:10],
                        "title": cand.get("title", ""),
                        "url": cand.get("url", ""),
                        "relevant": "",
                    }
                )
                rows += 1
    print(f"wrote {csv_path} ({rows} candidate rows)")
    return 0


def import_labels(csv_path: Path, out_path: Path) -> int:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    grouped: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        if str(row.get("relevant", "")).strip().lower() not in TRUTHY:
            continue
        rid = str(row.get("report_id", "")).strip()
        if not rid:
            continue
        key = (str(row.get("query", "")).strip(), str(row.get("country", "")).strip())
        grouped.setdefault(key, [])
        if rid not in grouped[key]:
            grouped[key].append(rid)
    golden = [{"query": q, "relevant": ids, "country": c} for (q, c), ids in grouped.items()]
    out_path.write_text(json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(golden)} labeled queries)")
    if not golden:
        print("warning: no relevant rows found; golden set would be empty")
    return 0 if golden else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Golden-set labeling CSV helper")
    ap.add_argument("--mode", choices=["export", "import"], required=True)
    ap.add_argument("--draft", default=str(ROOT / "data" / "eval" / "golden_set_draft.json"))
    ap.add_argument("--csv", default=str(ROOT / "data" / "eval" / "golden_set_labeling.csv"))
    ap.add_argument("--out", default=str(ROOT / "data" / "eval" / "golden_set.json"))
    args = ap.parse_args()
    if args.mode == "export":
        return export(Path(args.draft), Path(args.csv))
    return import_labels(Path(args.csv), Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
