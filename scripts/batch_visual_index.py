#!/usr/bin/env python3
"""Download a manifest, build one PixelRAG index, and classify all tiles locally."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import boto3
import numpy as np
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--provider", choices=("ollama", "openrouter", "gemini"), default="ollama")
    parser.add_argument("--base-url", default=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    parser.add_argument("--gemini-api-key", default=os.getenv("GEMINI_API_KEY", ""))
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--tile-limit", type=int, default=5000)
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    load_dotenv()
    required = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    if not all(os.getenv(name) for name in required):
        raise SystemExit("R2 credentials are required in the local environment")
    records = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.limit:
        records = records[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    work = args.work if args.work else Path(tempfile.mkdtemp(prefix="sightline-visual-batch-"))
    work.mkdir(parents=True, exist_ok=True)
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    try:
        source = work / "source"
        source.mkdir()
        article_map = {}
        for article_id, record in enumerate(records):
            report_id = int(record["report_id"])
            filename = f"{article_id:06d}_{report_id}.pdf"
            client.download_file(os.environ["R2_BUCKET"], record["source_object_key"], str(source / filename))
            article_map[str(article_id)] = {"report_id": report_id, **record}
            print(f"downloaded {article_id + 1}/{len(records)} report {report_id}", flush=True)

        index_dir = work / "index"
        subprocess.run(
            [
                "pixelrag",
                "index",
                "build",
                "--source",
                str(source),
                "--source-type",
                "local",
                "--output",
                str(index_dir),
                "--device",
                args.device,
                "--force",
            ],
            check=True,
        )
        captions = work / "captions.json"
        caption_cmd = [
            os.environ.get("PYTHON", "python3"),
            "scripts/caption_pixelrag_tiles.py",
            str(index_dir / "tiles"),
            "--output",
            str(captions),
            "--provider",
            args.provider,
            "--model",
            args.model,
            "--base-url",
            args.base_url,
            "--ollama-url",
            os.getenv("LOCAL_OLLAMA_URL", "http://127.0.0.1:11434"),
            "--limit",
            str(args.tile_limit),
        ]
        if args.provider == "gemini":
            caption_cmd += ["--gemini-api-key", args.gemini_api_key]
        subprocess.run(caption_cmd, check=True)
        caption_map = json.loads(captions.read_text(encoding="utf-8"))
        metadata = np.load(index_dir / "metadata.npz", allow_pickle=True)
        units = []
        for article_id, tile_index in zip(metadata["article_ids"].tolist(), metadata["tile_indices"].tolist(), strict=True):
            report = article_map[str(article_id)]
            result = caption_map.get(f"{article_id}:{tile_index:04d}", {})
            decorative = bool(result.get("is_decorative", False))
            units.append(
                {
                    "unit_id": f"{report['report_id']}-tile-{tile_index:04d}",
                    "report_id": report["report_id"],
                    "page_number": int(tile_index) + 1,
                    "visual_type": result.get("visual_type", "visual"),
                    "caption": result.get("caption", f"Visual document tile {tile_index + 1}"),
                    "asset_key": f"r2://{report['source_object_key']}#tile-{tile_index:04d}",
                    "relevance": float(result.get("relevance", 0.5)),
                    "is_decorative": decorative,
                    "index_for_retrieval": not decorative,
                }
            )
        (args.output / "visual_units.jsonl").write_text(
            "\n".join(json.dumps(unit, ensure_ascii=False) for unit in units) + "\n", encoding="utf-8"
        )
        (args.output / "manifest.json").write_text(
            json.dumps(
                {"pipeline_version": f"pixelrag-{args.provider}-v1", "model": args.model, "reports": len(records), "units": len(units)},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"reports": len(records), "units": len(units), "output": str(args.output)}))
    finally:
        if not args.work:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
