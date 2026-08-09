#!/usr/bin/env python3
"""Assemble a partial or complete multi-document PixelRAG visual package."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--captions-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    captions = json.loads(args.captions_json.read_text(encoding="utf-8"))
    source_files = sorted(args.source_dir.glob("*.pdf"))
    reports = {}
    for article_id, source in enumerate(source_files):
        match = re.search(r"_(\d+)\.pdf$", source.name)
        if match:
            reports[str(article_id)] = int(match.group(1))
    metadata = np.load(args.index_dir / "metadata.npz", allow_pickle=True)
    units = []
    for article_id, tile_index in zip(metadata["article_ids"].tolist(), metadata["tile_indices"].tolist(), strict=True):
        report_id = reports.get(str(article_id))
        result = captions.get(f"{article_id}:{tile_index:04d}")
        if report_id is None or result is None:
            continue
        decorative = bool(result.get("is_decorative", False))
        units.append(
            {
                "unit_id": f"{report_id}-tile-{tile_index:04d}",
                "report_id": report_id,
                "page_number": int(tile_index) + 1,
                "visual_type": result.get("visual_type", "visual"),
                "caption": result.get("caption", "Visual document tile"),
                "asset_key": f"r2://source-pdfs/{report_id}#tile-{tile_index:04d}",
                "relevance": float(result.get("relevance", 0.5)),
                "is_decorative": decorative,
                "index_for_retrieval": not decorative,
            }
        )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "visual_units.jsonl").write_text(
        "\n".join(json.dumps(unit, ensure_ascii=False) for unit in units) + "\n", encoding="utf-8"
    )
    (args.output / "manifest.json").write_text(
        json.dumps({"pipeline_version": "pixelrag-ollama-v1", "units": len(units)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"units": len(units), "reports": len({unit['report_id'] for unit in units})}))


if __name__ == "__main__":
    main()
