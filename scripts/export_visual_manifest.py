#!/usr/bin/env python3
"""Export reports with R2 PDFs that have not received visual analysis yet."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("visual-manifest.json"))
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    conn = sqlite3.connect(config.DB_PATH)
    rows = conn.execute(
        """SELECT r.report_id, r.title, r.date, r.source_object_key
        FROM reports r
        LEFT JOIN visual_units v ON v.report_id = r.report_id
        WHERE r.source_object_key IS NOT NULL AND r.source_object_key <> ''
          AND v.report_id IS NULL
        GROUP BY r.report_id
        ORDER BY r.date DESC, r.report_id DESC
        LIMIT ?""",
        (args.limit,),
    ).fetchall()
    conn.close()
    manifest = [
        {"report_id": row[0], "title": row[1], "date": row[2], "source_object_key": row[3]}
        for row in rows
    ]
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "reports": len(manifest)}))


if __name__ == "__main__":
    main()
