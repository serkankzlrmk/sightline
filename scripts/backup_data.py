#!/usr/bin/env python3
"""Create consistent SQLite/Chroma backups locally and optionally upload to R2."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import config


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sqlite_snapshot(source: Path, target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    reader = sqlite3.connect(source)
    writer = sqlite3.connect(target)
    try:
        reader.backup(writer)
        integrity = writer.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        writer.close()
        reader.close()
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {source}: {integrity}")
    return {"source": str(source), "size": target.stat().st_size, "sha256": checksum(target), "integrity": integrity}


def chroma_archive(source: Path, target: Path) -> dict:
    with tarfile.open(target, "w:gz") as archive:
        for path in source.rglob("*"):
            if path.is_file() and "cache" not in path.parts:
                archive.add(path, arcname=Path(source.name) / path.relative_to(source))
    return {"source": str(source), "size": target.stat().st_size, "sha256": checksum(target)}


def upload_r2(files: list[Path], object_prefix: str) -> None:
    if not config.R2_BACKUP_ENABLED:
        return
    required = (config.R2_ACCESS_KEY_ID, config.R2_SECRET_ACCESS_KEY, config.R2_BUCKET, config.R2_ENDPOINT_URL)
    if not all(required):
        raise RuntimeError("R2_BACKUP_ENABLED=true requires R2 credentials, bucket, and endpoint")
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=config.R2_ENDPOINT_URL,
        aws_access_key_id=config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
    )
    for path in files:
        client.upload_file(str(path), config.R2_BUCKET, f"{object_prefix}/{path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="backups")
    args = parser.parse_args()
    backup_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    temp_dir = Path(tempfile.mkdtemp(prefix="sightline-backup-"))
    output = Path(args.output_dir) / backup_id
    try:
        files: list[Path] = []
        manifest = {"backup_id": backup_id, "created_at": datetime.now(UTC).isoformat(), "files": {}}
        for name, source in {"reliefweb.db": Path(config.DB_PATH), "chats.db": Path(config.CHATS_DB_PATH)}.items():
            target = temp_dir / name
            manifest["files"][name] = sqlite_snapshot(source, target)
            files.append(target)
        chroma = temp_dir / "chroma.tar.gz"
        manifest["files"]["chroma.tar.gz"] = chroma_archive(Path(config.CHROMA_DIR), chroma)
        files.append(chroma)
        manifest_path = temp_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        files.append(manifest_path)
        output.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copy2(path, output / path.name)
        upload_r2(files, f"{config.R2_BACKUP_PREFIX}/daily/{backup_id}")
        print(json.dumps({"backup_id": backup_id, "local_path": str(output), "r2": config.R2_BACKUP_ENABLED}))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
