#!/usr/bin/env python3
"""Reset the live ReliefWeb SQLite and Chroma stores after a backup."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true", help="Required destructive confirmation")
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit("Refusing to reset without --confirm")

    database = Path(config.DB_PATH)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)
    chroma = Path(config.CHROMA_DIR)
    if chroma.exists():
        # CHROMA_DIR is commonly a mounted Docker volume; remove its contents,
        # not the mountpoint itself.
        for child in chroma.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
    else:
        chroma.mkdir(parents=True, exist_ok=True)
    print(f"Reset complete: {database} and {chroma}; chats DB preserved at {config.CHATS_DB_PATH}")


if __name__ == "__main__":
    main()
