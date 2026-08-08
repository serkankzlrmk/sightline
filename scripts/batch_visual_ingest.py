#!/usr/bin/env python3
"""Process R2 PDFs locally with PixelRAG + Ollama and build one import package."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import boto3
from dotenv import load_dotenv


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--tile-limit", type=int, default=200)
    args = parser.parse_args()
    load_dotenv()
    required = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    if not all(os.getenv(name) for name in required):
        raise SystemExit("R2 credentials are required in the local environment")

    records = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.limit:
        records = records[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    combined = args.output / "visual_units.jsonl"
    failures = []
    processed = 0
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    with combined.open("w", encoding="utf-8") as output_stream:
        for position, record in enumerate(records, 1):
            report_id = int(record["report_id"])
            temp_dir = Path(tempfile.mkdtemp(prefix=f"sightline-visual-{report_id}-"))
            try:
                source_dir = temp_dir / "source"
                source_dir.mkdir()
                pdf_path = source_dir / "report.pdf"
                client.download_file(os.environ["R2_BUCKET"], record["source_object_key"], str(pdf_path))
                index_dir = temp_dir / "index"
                run(
                    [
                        "pixelrag",
                        "index",
                        "build",
                        "--source",
                        str(source_dir),
                        "--source-type",
                        "local",
                        "--output",
                        str(index_dir),
                        "--device",
                        args.device,
                        "--force",
                    ]
                )
                captions = temp_dir / "captions.json"
                run(
                    [
                        os.environ.get("PYTHON", "python3"),
                        "scripts/caption_pixelrag_tiles.py",
                        str(index_dir / "tiles"),
                        "--output",
                        str(captions),
                        "--provider",
                        "ollama",
                        "--model",
                        args.model,
                        "--ollama-url",
                        os.getenv("LOCAL_OLLAMA_URL", "http://127.0.0.1:11434"),
                        "--limit",
                        str(args.tile_limit),
                    ]
                )
                package_dir = temp_dir / "package"
                run(
                    [
                        os.environ.get("PYTHON", "python3"),
                        "scripts/pixelrag_to_package.py",
                        "--index-dir",
                        str(index_dir),
                        "--report-id",
                        str(report_id),
                        "--captions-json",
                        str(captions),
                        "--output",
                        str(package_dir),
                    ]
                )
                for line in (package_dir / "visual_units.jsonl").read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        output_stream.write(line + "\n")
                processed += 1
                print(f"[{position}/{len(records)}] processed report {report_id}", flush=True)
            except Exception as exc:
                failures.append({"report_id": report_id, "error": str(exc)})
                print(f"[{position}/{len(records)}] failed report {report_id}: {exc}", flush=True)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "pipeline_version": "pixelrag-ollama-v1",
                "model": args.model,
                "processed_reports": processed,
                "requested_reports": len(records),
                "failures": failures,
            },
            indent=2,
        )
        + "\n",
    )
    print(json.dumps({"processed": processed, "requested": len(records), "failures": len(failures)}))


if __name__ == "__main__":
    main()
