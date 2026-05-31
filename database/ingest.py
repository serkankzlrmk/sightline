"""
ReliefWeb Database Ingestion Script

Two modes:
  1. In-memory ingest from API (recommended — no disk writes):
     python ingest.py --from-api 4205377 4192591 ...

  2. Legacy folder scan (for pre-downloaded reports):
     python ingest.py                          # scan reliefweb_downloads/
     python ingest.py --dir my_downloads       # custom folder

Other options:
    python ingest.py --db custom.db           # custom database path
    python ingest.py --stats                  # show current DB + vector stats only
    python ingest.py --sync-chroma            # push SQLite chunks → ChromaDB

Deduplication: reports already in the DB are skipped automatically.
Running this multiple times is safe.

After running this script, the knowledge base (reliefweb_chroma/) is ready
for semantic search via the search_knowledge_base agent tool or VectorStore.search().
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Suppress TensorRT "nvinfer_10.dll not found" warnings from ONNX Runtime.
os.environ["ORT_LOGGING_LEVEL"] = "3"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

# Allow running from repo root (reliefweb_api/ is in project root)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reliefweb_api.db_manager import DatabaseManager, DEFAULT_DB_PATH, CHUNK_SIZE, CHUNK_OVERLAP
from reliefweb_api.ingest_pipeline import is_ingested, auto_ingest, CHROMA_DIR
from reliefweb_api.vector_store import VectorStore


# ============================================================================
# SYNC: push SQLite chunks → ChromaDB (migration / re-index)
# ============================================================================

def sync_sqlite_to_chroma(db: DatabaseManager, vs: VectorStore) -> dict:
    """
    Read all reports from SQLite and push any that are missing from ChromaDB.
    Useful for migration and re-indexing without re-downloading.
    """
    conn = db._connect()
    reports = conn.execute(
        "SELECT report_id, title, date, source, countries, themes, url FROM reports"
    ).fetchall()

    pushed = 0
    skipped = 0

    for row in reports:
        rid = row["report_id"]
        if vs.report_exists(rid):
            skipped += 1
            continue

        # Read chunks for this report
        chunk_rows = conn.execute(
            "SELECT chunk_index, source_type, content FROM chunks WHERE report_id = ? ORDER BY chunk_index",
            (rid,),
        ).fetchall()

        if not chunk_rows:
            skipped += 1
            continue

        chunks = [{"source_type": r["source_type"], "content": r["content"]} for r in chunk_rows]

        # Build minimal metadata dict compatible with VectorStore.add_report
        import json as _json
        try:
            countries_list = _json.loads(row["countries"] or "[]")
        except Exception:
            countries_list = []
        try:
            themes_list = _json.loads(row["themes"] or "[]")
        except Exception:
            themes_list = []

        report_meta = {
            "title": row["title"],
            "date": {"original": row["date"]},
            "source": [{"shortname": row["source"]}],
            "countries": [{"name": c, "shortname": c} for c in countries_list],
            "themes": [{"name": t} for t in themes_list],
            "url": row["url"] or "",
        }

        vs.add_report(rid, chunks, report_meta)
        pushed += 1
        print(f"  → {rid}  embedded {len(chunks)} chunks  {row['title'][:55]}")

    conn.close()
    return {"pushed": pushed, "skipped": skipped}


# ============================================================================
# FOLDER SCANNER
# ============================================================================

def find_report_folders(downloads_dir: str):
    """
    Yield (report_id, folder, content_path, pdf_path, metadata)
    for every report folder found under downloads_dir.
    """
    root = Path(downloads_dir)
    if not root.exists():
        print(f"[ERROR] Downloads folder not found: {root.resolve()}")
        return

    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue

        metadata_files = list(folder.glob("*_metadata.json"))
        content_files = list(folder.glob("*_content.txt"))
        pdf_files = list(folder.glob("*.pdf"))

        if not metadata_files:
            continue

        try:
            with open(metadata_files[0], encoding="utf-8") as f:
                meta = json.load(f)
            report_id = int(meta.get("id", 0))
            if report_id < 1:
                continue
        except Exception:
            continue

        yield (
            report_id,
            folder,
            content_files[0] if content_files else None,
            pdf_files[0] if pdf_files else None,
            meta,
        )


# ============================================================================
# MAIN CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ingest ReliefWeb reports into SQLite + ChromaDB"
    )
    parser.add_argument("--dir", default="reliefweb_downloads", help="Downloads folder (legacy mode)")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument("--chroma", default=CHROMA_DIR, help="ChromaDB persist directory")
    parser.add_argument("--stats", action="store_true", help="Show DB + vector stats and exit")
    parser.add_argument("--sync-chroma", action="store_true",
                        help="Push all SQLite chunks to ChromaDB (migration / re-index)")
    parser.add_argument("--from-api", nargs="+", type=int,
                        help="Ingest report IDs directly from ReliefWeb API (in-memory, no disk writes)")
    args = parser.parse_args()

    # ── In-memory API ingest mode ────────────────────────────────
    if args.from_api:
        from reliefweb_api.ingest_pipeline import is_ingested, is_ingested_with_pdf, ingest_from_api
        print("=" * 60)
        print("IN-MEMORY INGEST FROM RELIEFWEB API")
        print("=" * 60)
        print(f"  Reports:  {len(args.from_api)}")
        print(f"  SQLite:   {Path(args.db).resolve()}")
        print(f"  ChromaDB: {Path(args.chroma).resolve()}")
        print()

        ingested = skipped = errors = 0
        for rid in args.from_api:
            if is_ingested(rid, args.db) and is_ingested_with_pdf(rid, args.db):
                skipped += 1
                print(f"  ~ {rid}  (already in DB with PDF)")
                continue

            result = ingest_from_api(rid, db_path=args.db, chroma_dir=args.chroma)
            if result.get("success"):
                ingested += 1
                pdf_tag = "[PDF]" if result.get("has_pdf") else "     "
                txt_tag = "[TXT]" if result.get("has_content") else "     "
                n = result.get("chunks_added", 0)
                print(f"  + {rid}  {pdf_tag}{txt_tag}  ({n} chunks)")
            else:
                errors += 1
                print(f"  ! {rid}  ERROR: {result.get('error', 'unknown')}")

        print()
        print(f"  Ingested: {ingested}  |  Skipped: {skipped}  |  Errors: {errors}")
        return

    if args.sync_chroma:
        print("=" * 60)
        print("SYNC SQLite → ChromaDB")
        print("=" * 60)
        db = DatabaseManager(args.db)
        vs = VectorStore(args.chroma)
        result = sync_sqlite_to_chroma(db, vs)
        db.close()
        v_stats = vs.get_stats()
        print()
        print(f"  Pushed:   {result['pushed']} reports")
        print(f"  Skipped:  {result['skipped']} (already in ChromaDB)")
        print(f"  ChromaDB chunks total: {v_stats['total_chunks']}")
        return

    if args.stats:
        db = DatabaseManager(args.db)
        stats = db.get_stats()
        db.close()
        vs = VectorStore(args.chroma)
        v_stats = vs.get_stats()
        print("\n=== DATABASE STATS ===")
        print(f"  SQLite reports:   {stats['reports']}")
        print(f"  SQLite chunks:    {stats['chunks']}")
        print(f"  With PDF:         {stats['with_pdf']}")
        print(f"  With content:     {stats['with_content']}")
        print(f"  SQLite size:      {stats['db_size_kb']} KB")
        print(f"  SQLite location:  {Path(args.db).resolve()}")
        print()
        print("=== VECTOR STORE STATS ===")
        print(f"  ChromaDB chunks:  {v_stats['total_chunks']}")
        print(f"  ChromaDB dir:     {v_stats['persist_dir']}")
        return

    print("=" * 60)
    print("RELIEFWEB DATABASE INGEST  (SQLite + ChromaDB)")
    print("=" * 60)
    print(f"  Source:      {Path(args.dir).resolve()}")
    print(f"  SQLite:      {Path(args.db).resolve()}")
    print(f"  ChromaDB:    {Path(args.chroma).resolve()}")
    print(f"  Chunk size:  {CHUNK_SIZE} chars  |  Overlap: {CHUNK_OVERLAP} chars")
    print()

    inserted = skipped = errors = 0

    for report_id, folder, content_path, pdf_path, metadata in find_report_folders(args.dir):
        title = metadata.get("title", "")[:55]

        if is_ingested(report_id, args.db):
            skipped += 1
            print(f"  ~ {report_id}  (already in DB)  {title}")
            continue

        result = auto_ingest(report_id, args.dir, db_path=args.db, chroma_dir=args.chroma)

        if result.get("success"):
            inserted += 1
            pdf_tag = "[PDF]" if result.get("has_pdf") else "     "
            txt_tag = "[TXT]" if result.get("has_content") else "     "
            n = result.get("chunks_added", 0)
            print(f"  + {report_id}  {pdf_tag}{txt_tag}  {title}  ({n} chunks)")
        else:
            errors += 1
            print(f"  ! {report_id}  ERROR: {result.get('error', 'unknown')}")

    # Final stats
    db = DatabaseManager(args.db)
    stats = db.get_stats()
    db.close()
    vs = VectorStore(args.chroma)
    v_stats = vs.get_stats()

    print()
    print("=" * 60)
    print("COMPLETE")
    print(f"  Inserted:  {inserted} new reports")
    print(f"  Skipped:   {skipped} (already in DB)")
    print(f"  Errors:    {errors}")
    print()
    print("DB TOTALS")
    print(f"  SQLite   — Reports: {stats['reports']} | Chunks: {stats['chunks']} | {stats['db_size_kb']} KB")
    print(f"  ChromaDB — Chunks (embeddings): {v_stats['total_chunks']}")
    print()


if __name__ == "__main__":
    main()
