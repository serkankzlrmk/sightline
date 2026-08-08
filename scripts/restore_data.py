#!/usr/bin/env python3
"""Restore a backup into an isolated directory; never overwrites live data."""

from __future__ import annotations

import argparse
import json
import shutil
import tarfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit("Refusing to restore without --confirm")
    manifest = json.loads((args.backup_dir / "manifest.json").read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, metadata in manifest["files"].items():
        source = args.backup_dir / name
        if metadata["sha256"] != __import__("hashlib").sha256(source.read_bytes()).hexdigest():
            raise SystemExit(f"Checksum mismatch: {source}")
        if name == "chroma.tar.gz":
            with tarfile.open(source, "r:gz") as archive:
                archive.extractall(args.output_dir, filter="data")
        else:
            shutil.copy2(source, args.output_dir / name)
    print(f"Restored isolated backup to {args.output_dir}")


if __name__ == "__main__":
    main()
