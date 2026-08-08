#!/usr/bin/env python3
"""Import a local PixelRAG/vision package into SQLite and ChromaDB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import config
from reliefweb_api.db_manager import DatabaseManager
from reliefweb_api.vector_store import VectorStore


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.package_dir / "manifest.json").read_text(encoding="utf-8"))
    version = manifest.get("pipeline_version", "visual-v1")
    rows = [json.loads(line) for line in (args.package_dir / "visual_units.jsonl").read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit("Package contains no visual units")

    db = DatabaseManager(str(config.DB_PATH))
    conn = sqlite3.connect(config.DB_PATH)
    units = []
    try:
        now = datetime.now(UTC).isoformat()
        for row in rows:
            report_id = int(row["report_id"])
            if not db.report_exists(report_id):
                raise ValueError(f"Unknown report_id: {report_id}")
            report_meta = conn.execute(
                "SELECT title, date, source, url FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            unit_id = str(row.get("unit_id") or f"{report_id}-p{int(row['page_number']):04d}-{row['visual_type']}")
            caption = str(row["caption"]).strip()
            if not caption:
                continue
            values = (
                unit_id,
                report_id,
                int(row["page_number"]),
                row.get("visual_type", "unknown"),
                caption,
                row.get("asset_key"),
                float(row.get("relevance", 0)),
                int(bool(row.get("is_decorative", False))),
                int(bool(row.get("index_for_retrieval", True))),
                row.get("pipeline_version", version),
                row.get("checksum"),
                now,
            )
            conn.execute(
                """INSERT OR REPLACE INTO visual_units
                (unit_id, report_id, page_number, visual_type, caption, asset_key,
                 relevance, is_decorative, index_for_retrieval, pipeline_version,
                 checksum, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            units.append(
                {
                    **row,
                    "unit_id": unit_id,
                    "pipeline_version": values[9],
                    "title": report_meta[0] if report_meta else "",
                    "date": report_meta[1] if report_meta else "",
                    "source": report_meta[2] if report_meta else "",
                    "url": report_meta[3] if report_meta else "",
                }
            )
        conn.commit()
    finally:
        conn.close()
        db.close()

    added = VectorStore(str(config.CHROMA_DIR)).add_visual_units(units)
    print(json.dumps({"package": str(args.package_dir), "units": len(units), "indexed": added}))


if __name__ == "__main__":
    main()
