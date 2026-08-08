#!/usr/bin/env python3
"""Convert a PixelRAG FAISS output into Sightline's portable package format."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--captions-json", type=Path, help="Mapping tile index to caption/type")
    args = parser.parse_args()
    metadata = np.load(args.index_dir / "metadata.npz", allow_pickle=True)
    captions = json.loads(args.captions_json.read_text(encoding="utf-8")) if args.captions_json else {}
    tile_dirs = list((args.index_dir / "tiles").glob("*.tiles"))
    if not tile_dirs:
        raise SystemExit("No PixelRAG tile directory found")

    args.output.mkdir(parents=True, exist_ok=True)
    assets = args.output / "assets"
    assets.mkdir(exist_ok=True)
    units = []
    for tile_index in metadata["tile_indices"].tolist():
        source = next((path / f"tile_{tile_index:04d}.jpg" for path in tile_dirs if (path / f"tile_{tile_index:04d}.jpg").exists()), None)
        if source is None:
            continue
        caption_data = captions.get(str(tile_index), captions.get(tile_index, {}))
        if isinstance(caption_data, str):
            caption_data = {"caption": caption_data}
        asset_name = f"tile_{tile_index:04d}.jpg"
        shutil.copy2(source, assets / asset_name)
        units.append(
            {
                "unit_id": f"{args.report_id}-tile-{tile_index:04d}",
                "report_id": args.report_id,
                "page_number": int(tile_index) + 1,
                "visual_type": caption_data.get("visual_type", "visual"),
                "caption": caption_data.get("caption", f"Visual document tile {tile_index + 1}"),
                "asset_key": f"assets/{asset_name}",
                "relevance": float(caption_data.get("relevance", 0.5)),
                "is_decorative": bool(caption_data.get("is_decorative", False)),
                "index_for_retrieval": not bool(caption_data.get("is_decorative", False)),
                "tile_index": int(tile_index),
            }
        )
    (args.output / "visual_units.jsonl").write_text(
        "\n".join(json.dumps(unit, ensure_ascii=False) for unit in units) + "\n", encoding="utf-8"
    )
    (args.output / "manifest.json").write_text(
        json.dumps({"report_id": args.report_id, "pipeline_version": "pixelrag-v1", "unit_count": len(units)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"report_id": args.report_id, "units": len(units), "package": str(args.output)}))


if __name__ == "__main__":
    main()
