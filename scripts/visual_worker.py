#!/usr/bin/env python3
"""Build a portable visual package from a local or R2 PDF."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path


def download_from_r2(key: str, target: Path) -> None:
    import boto3

    required = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    if not all(os.getenv(name) for name in required):
        raise RuntimeError("R2 environment is incomplete")
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    client.download_file(os.environ["R2_BUCKET"], key, str(target))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--r2-key")
    parser.add_argument("--units-jsonl", type=Path, required=True, help="PixelRAG adapter output")
    parser.add_argument("--pipeline-version", default="pixelrag-v1")
    args = parser.parse_args()
    if bool(args.pdf) == bool(args.r2_key):
        raise SystemExit("Provide exactly one of --pdf or --r2-key")
    if not args.units_jsonl.exists():
        raise SystemExit(f"Visual units file not found: {args.units_jsonl}")

    temp_dir = Path(tempfile.mkdtemp(prefix="sightline-visual-"))
    try:
        source_pdf = temp_dir / "source.pdf"
        if args.pdf:
            shutil.copy2(args.pdf, source_pdf)
        else:
            download_from_r2(args.r2_key, source_pdf)
        units = []
        for line in args.units_jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            unit = json.loads(line)
            if int(unit["report_id"]) != args.report_id:
                raise ValueError("Visual unit report_id does not match --report-id")
            unit["pipeline_version"] = args.pipeline_version
            units.append(unit)
        if not units:
            raise SystemExit("No visual units supplied")
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "manifest.json").write_text(
            json.dumps(
                {
                    "report_id": args.report_id,
                    "pipeline_version": args.pipeline_version,
                    "source_r2_key": args.r2_key,
                    "unit_count": len(units),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (args.output / "visual_units.jsonl").write_text(
            "\n".join(json.dumps(unit, ensure_ascii=False) for unit in units) + "\n", encoding="utf-8"
        )
        print(json.dumps({"report_id": args.report_id, "package": str(args.output), "units": len(units)}))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
