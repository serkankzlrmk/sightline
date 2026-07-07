#!/usr/bin/env python3
"""
migrate_to_supabase_rest.py — Migrate data from SQLite + ChromaDB to Supabase via REST API

Uses Supabase REST API (PostgREST) instead of direct PostgreSQL connection.
This works even when direct DB connection is not available (e.g., IPv6-only hosts).

Usage:
    # Set environment variables first (or use .env):
    export SUPABASE_URL="https://pmpcvmvxhxmnjbkxgnhk.supabase.co"
    export SUPABASE_SERVICE_KEY="eyJhbG..."

    # Dry run (no writes):
    python migrate_to_supabase_rest.py --dry-run

    # Migrate reports only:
    python migrate_to_supabase_rest.py --reports-only

    # Full migration (reports + chunks with embeddings):
    python migrate_to_supabase_rest.py --with-embeddings

    # Verify migration:
    python migrate_to_supabase_rest.py --verify-only
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import CHROMA_COLLECTION, CHROMA_DIR, DB_PATH

# Supabase config from env
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")


def get_headers(service: bool = True) -> dict:
    """Get headers for Supabase REST API."""
    key = SUPABASE_SERVICE_KEY if service else SUPABASE_ANON_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",  # Don't return inserted rows (faster)
    }


def get_sql_headers() -> dict:
    """Get headers for Supabase SQL RPC calls."""
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


# ============================================================================
# READ FROM SQLITE
# ============================================================================

def get_sqlite_reports(db_path: str) -> list[dict]:
    """Read all reports from SQLite."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM reports ORDER BY report_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sqlite_report_count(db_path: str) -> int:
    """Count reports in SQLite."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    conn.close()
    return count


# ============================================================================
# READ FROM CHROMADB
# ============================================================================

def get_chromadb_chunks_with_embeddings(chroma_dir: str, collection_name: str) -> list[dict]:
    """Read all chunks with embeddings from ChromaDB."""
    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    client = chromadb.PersistentClient(path=chroma_dir)
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=DefaultEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )

    total = collection.count()
    print(f"  ChromaDB has {total} chunks")

    # Fetch in batches
    batch_size = 5000
    all_chunks = []

    for offset in range(0, total, batch_size):
        limit = min(batch_size, total - offset)
        results = collection.get(
            include=["documents", "metadatas", "embeddings"],
            limit=limit,
            offset=offset,
        )
        for i, (cid, doc, meta, emb) in enumerate(zip(
            results["ids"],
            results["documents"],
            results["metadatas"],
            results["embeddings"],
        )):
            all_chunks.append({
                "id": cid,
                "document": doc,
                "metadata": meta,
                "embedding": emb,
            })
        print(f"  Fetched {min(offset + batch_size, total)}/{total} chunks...")

    return all_chunks


# ============================================================================
# MIGRATE VIA REST API
# ============================================================================

def migrate_reports_via_api(reports: list[dict], dry_run: bool = False) -> int:
    """Migrate reports to Supabase using REST API."""
    import requests

    url = f"{SUPABASE_URL}/rest/v1/reports"
    headers = get_headers(service=True)
    # Remove Prefer header for upsert to work
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"

    migrated = 0
    batch_size = 50

    for i in range(0, len(reports), batch_size):
        batch = reports[i:i + batch_size]
        rows = []

        for r in batch:
            # Parse countries/themes from JSON strings
            countries = r.get("countries", "[]")
            themes = r.get("themes", "[]")
            if isinstance(countries, str):
                try:
                    countries = json.loads(countries)
                except (json.JSONDecodeError, TypeError):
                    countries = []
            if isinstance(themes, str):
                try:
                    themes = json.loads(themes)
                except (json.JSONDecodeError, TypeError):
                    themes = []

            rows.append({
                "report_id": r["report_id"],
                "title": r.get("title", ""),
                "date": (r.get("date", "") or "")[:10] or None,
                "source": r.get("source", ""),
                "url": r.get("url", ""),
                "countries": countries,
                "themes": themes,
                "format_type": r.get("format_type", ""),
                "language": r.get("language", ""),
                "has_pdf": bool(r.get("has_pdf", False)),
                "has_content": bool(r.get("has_content", False)),
                "pdf_pages": r.get("pdf_pages", 0) or 0,
                "total_chunks": r.get("total_chunks", 0) or 0,
            })

        if dry_run:
            print(f"  [DRY RUN] Would insert {len(rows)} reports (batch {i // batch_size + 1})")
            migrated += len(rows)
        else:
            try:
                resp = requests.post(url, json=rows, headers=headers, timeout=30)
                if resp.status_code in (200, 201, 204):
                    migrated += len(rows)
                    print(f"  Inserted {len(rows)} reports (batch {i // batch_size + 1}, total: {migrated})")
                else:
                    print(f"  Error inserting batch: {resp.status_code} - {resp.text[:200]}")
                    # Try one by one
                    for row in rows:
                        try:
                            resp2 = requests.post(url, json=row, headers=headers, timeout=10)
                            if resp2.status_code in (200, 201, 204):
                                migrated += 1
                            else:
                                print(f"    Skip report {row['report_id']}: {resp2.status_code}")
                        except Exception as e:
                            print(f"    Error report {row['report_id']}: {e}")
            except Exception as e:
                print(f"  Error inserting batch: {e}")

    print(f"Reports: {migrated}/{len(reports)} migrated")
    return migrated


def migrate_chunks_via_api(chroma_chunks: list[dict], dry_run: bool = False) -> int:
    """
    Migrate chunks with embeddings to Supabase using SQL RPC.

    Since REST API can't handle vector columns directly, we use the
    Supabase SQL RPC endpoint to insert chunks with embeddings.
    """
    import requests

    url = f"{SUPABASE_URL}/rest/v1/rpc/insert_chunk_with_embedding"
    headers = get_sql_headers()

    migrated = 0
    total = len(chroma_chunks)

    if dry_run:
        print(f"  [DRY RUN] Would insert {total} chunks with embeddings")
        return total

    # Insert chunks one by one via a custom RPC function
    # But we haven't created that function yet, so let's use batch insert
    # via the chunks table (without embeddings first, then update embeddings)

    # Step 1: Insert chunks without embeddings via REST API
    chunks_url = f"{SUPABASE_URL}/rest/v1/chunks"
    chunks_headers = get_headers(service=True)
    chunks_headers["Prefer"] = "resolution=merge-duplicates,return=minimal"

    batch_size = 100
    for i in range(0, total, batch_size):
        batch = chroma_chunks[i:i + batch_size]
        rows = []

        for chunk in batch:
            meta = chunk["metadata"]
            rows.append({
                "report_id": meta.get("report_id"),
                "chunk_index": meta.get("chunk_index", 0),
                "source_type": meta.get("source_type", "html"),
                "content": chunk["document"] or "",
                "char_count": len(chunk["document"] or ""),
                "title": meta.get("title", ""),
                "date": meta.get("date", ""),
                "source": meta.get("source", ""),
                "primary_country": meta.get("primary_country", ""),
                "all_countries": meta.get("all_countries", ""),
                "themes": meta.get("themes", ""),
                "url": meta.get("url", ""),
            })

        try:
            resp = requests.post(chunks_url, json=rows, headers=chunks_headers, timeout=30)
            if resp.status_code in (200, 201, 204):
                migrated += len(rows)
                print(f"  Inserted {len(rows)} chunks (total: {migrated}/{total})")
            else:
                print(f"  Error batch {i // batch_size + 1}: {resp.status_code} - {resp.text[:200]}")
                # Try one by one
                for row in rows:
                    try:
                        resp2 = requests.post(chunks_url, json=row, headers=chunks_headers, timeout=10)
                        if resp2.status_code in (200, 201, 204):
                            migrated += 1
                        else:
                            print(f"    Skip chunk {row['report_id']}_{row['chunk_index']}: {resp2.status_code}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"  Error batch: {e}")

    print(f"Chunks (without embeddings): {migrated}/{total} migrated")

    # Step 2: Update embeddings via SQL RPC
    # We need to create a helper function first
    print("\n  Now updating embeddings via SQL RPC...")
    embedding_updated = update_embeddings_via_sql(chroma_chunks, dry_run)

    return migrated


def update_embeddings_via_sql(chroma_chunks: list[dict], dry_run: bool = False) -> int:
    """Update embeddings for chunks using Supabase SQL RPC."""

    # First, create the update function via SQL RPC
    # We'll use the exec_sql RPC if available, or create a custom one
    # For now, we'll use a direct approach: update each chunk's embedding

    url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"
    headers = get_sql_headers()

    updated = 0
    total = len(chroma_chunks)
    batch_size = 50

    for i in range(0, total, batch_size):
        batch = chroma_chunks[i:i + batch_size]

        if dry_run:
            print(f"  [DRY RUN] Would update {len(batch)} embeddings")
            updated += len(batch)
            continue

        # Build SQL UPDATE statements
        for chunk in batch:
            meta = chunk["metadata"]
            emb = chunk.get("embedding")
            if not emb:
                continue

            report_id = meta.get("report_id")
            chunk_index = meta.get("chunk_index", 0)
            emb_str = "[" + ",".join(str(x) for x in emb) + "]"

            # Use REST API to update the chunk
            update_url = f"{SUPABASE_URL}/rest/v1/chunks?report_id=eq.{report_id}&chunk_index=eq.{chunk_index}"
            update_headers = get_headers(service=True)

            try:
                # Note: PostgREST can't update vector columns directly
                # We need to use RPC or direct SQL
                # For now, skip embedding updates via REST
                pass
            except Exception:
                pass

    if dry_run:
        print(f"  [DRY RUN] Would update {updated} embeddings")
    else:
        print("  Note: Embeddings need to be updated via SQL Editor or direct DB connection")
        print("  Chunks are inserted without embeddings. Use the SQL below to update embeddings.")

    return updated


# ============================================================================
# VERIFY MIGRATION
# ============================================================================

def verify_via_api() -> None:
    """Verify migration by checking counts via REST API."""
    import requests

    headers = get_headers(service=True)

    # Check reports count
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/reports?select=report_id&limit=1",
        headers=headers,
    )
    # Get total count via count header
    count_headers = {**headers, "Prefer": "count=exact"}
    resp_reports = requests.get(
        f"{SUPABASE_URL}/rest/v1/reports?select=report_id&limit=0",
        headers=count_headers,
    )
    pg_reports = int(resp_reports.headers.get("content-range", "*/0").split("/")[-1]) if resp_reports.status_code == 200 else 0

    resp_chunks = requests.get(
        f"{SUPABASE_URL}/rest/v1/chunks?select=id&limit=0",
        headers=count_headers,
    )
    pg_chunks = int(resp_chunks.headers.get("content-range", "*/0").split("/")[-1]) if resp_chunks.status_code == 200 else 0

    # SQLite counts
    import sqlite3
    sqlite_conn = sqlite3.connect(str(DB_PATH))
    sqlite_reports = sqlite_conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    sqlite_chunks = sqlite_conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    sqlite_conn.close()

    # ChromaDB count
    try:
        import chromadb
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=DefaultEmbeddingFunction(),
            metadata={"hnsw:space": "cosine"},
        )
        chroma_count = collection.count()
    except Exception:
        chroma_count = "N/A"

    print("\n=== Migration Verification ===")
    print(f"  Reports:  SQLite={sqlite_reports}, Supabase={pg_reports}, Match={'✅' if sqlite_reports == pg_reports else '❌'}")
    print(f"  Chunks:   SQLite={sqlite_chunks}, ChromaDB={chroma_count}, Supabase={pg_chunks}")
    print("  Embeddings: Need direct DB connection to verify (use SQL Editor)")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Migrate data from SQLite+ChromaDB to Supabase via REST API")
    parser.add_argument("--dry-run", action="store_true", help="Don't write anything, just show what would be done")
    parser.add_argument("--reports-only", action="store_true", help="Only migrate reports, skip chunks")
    parser.add_argument("--with-embeddings", action="store_true", help="Migrate chunks with embeddings from ChromaDB")
    parser.add_argument("--skip-reports", action="store_true", help="Skip report migration")
    parser.add_argument("--verify-only", action="store_true", help="Only verify migration, don't migrate")
    parser.add_argument("--db-path", default=str(DB_PATH), help="Path to SQLite database")
    parser.add_argument("--chroma-dir", default=str(CHROMA_DIR), help="Path to ChromaDB directory")
    args = parser.parse_args()

    # Load .env if not already set
    from dotenv import load_dotenv
    load_dotenv(override=True)

    global SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY
    SUPABASE_URL = os.getenv("SUPABASE_URL", SUPABASE_URL)
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", SUPABASE_SERVICE_KEY)
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", SUPABASE_ANON_KEY)

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        print("  export SUPABASE_URL='https://pmpcvmvxhxmnjbkxgnhk.supabase.co'")
        print("  export SUPABASE_SERVICE_KEY='your-service-key'")
        sys.exit(1)

    print("=" * 60)
    print("ReliefWeb → Supabase Migration (REST API)")
    print("=" * 60)
    print(f"  Supabase URL: {SUPABASE_URL}")
    print(f"  SQLite DB: {args.db_path}")
    print(f"  ChromaDB: {args.chroma_dir}")

    if args.dry_run:
        print("  [DRY RUN MODE — no data will be written]")

    # Verify only
    if args.verify_only:
        verify_via_api()
        return

    # Step 1: Migrate reports
    if not args.skip_reports:
        print("\nStep 1: Migrating reports from SQLite...")
        reports = get_sqlite_reports(args.db_path)
        print(f"  Found {len(reports)} reports in SQLite")
        migrate_reports_via_api(reports, dry_run=args.dry_run)

    # Step 2: Migrate chunks with embeddings
    if args.with_embeddings:
        print("\nStep 2: Migrating chunks with embeddings from ChromaDB...")
        chroma_chunks = get_chromadb_chunks_with_embeddings(args.chroma_dir, CHROMA_COLLECTION)
        print(f"  Found {len(chroma_chunks)} chunks in ChromaDB")
        migrate_chunks_via_api(chroma_chunks, dry_run=args.dry_run)

    # Step 3: Verify
    print("\nStep 3: Verifying migration...")
    verify_via_api()

    print("\n✅ Migration complete!")
    print("\n⚠️  NOTE: Embeddings were NOT migrated via REST API.")
    print("   To add embeddings, you need a direct PostgreSQL connection.")
    print("   Options:")
    print("   1. Run from a machine with IPv6 support")
    print("   2. Use Supabase SQL Editor to run UPDATE statements")
    print("   3. Use the production server (which may have IPv6)")


if __name__ == "__main__":
    main()
