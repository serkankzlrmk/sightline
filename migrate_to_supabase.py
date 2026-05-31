#!/usr/bin/env python3
"""
migrate_to_supabase.py — Migrate data from SQLite + ChromaDB to Supabase + pgvector

This script:
1. Reads all reports from SQLite and inserts them into Supabase
2. Reads all chunks from ChromaDB (with embeddings) and inserts them into Supabase
3. Verifies data integrity after migration

Usage:
    # Set environment variables first:
    export SUPABASE_URL="https://your-project.supabase.co"
    export SUPABASE_SERVICE_KEY="your-service-key"
    export SUPABASE_DB_URL="postgresql://postgres.your-ref:password@aws-0-region.pooler.supabase.com:6543/postgres"

    # Run migration:
    python migrate_to_supabase.py

    # Dry run (no writes):
    python migrate_to_supabase.py --dry-run

    # Migrate only reports (no chunks/embeddings):
    python migrate_to_supabase.py --reports-only

    # Migrate chunks with embeddings from ChromaDB:
    python migrate_to_supabase.py --with-embeddings
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH, CHROMA_DIR, CHROMA_COLLECTION


def get_sqlite_reports(db_path: str) -> List[Dict]:
    """Read all reports from SQLite."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM reports ORDER BY report_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sqlite_chunks(db_path: str) -> List[Dict]:
    """Read all chunks from SQLite."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM chunks ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_chromadb_chunks_with_embeddings(chroma_dir: str, collection_name: str) -> List[Dict]:
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


def create_supabase_schema(db_url: str):
    """Create the database schema in Supabase."""
    import psycopg2

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    print("Creating schema...")

    # Enable pgvector extension
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Reports table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            date DATE,
            source TEXT DEFAULT '',
            url TEXT DEFAULT '',
            countries JSONB DEFAULT '[]'::jsonb,
            themes JSONB DEFAULT '[]'::jsonb,
            format_type TEXT DEFAULT '',
            language TEXT DEFAULT '',
            has_pdf BOOLEAN DEFAULT FALSE,
            has_content BOOLEAN DEFAULT FALSE,
            pdf_pages INTEGER DEFAULT 0,
            total_chunks INTEGER DEFAULT 0,
            ingested_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # Chunks table with embedding column
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id SERIAL PRIMARY KEY,
            report_id INTEGER REFERENCES reports(report_id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            source_type TEXT DEFAULT 'html',
            content TEXT NOT NULL,
            char_count INTEGER DEFAULT 0,
            embedding vector(384),
            title TEXT DEFAULT '',
            date TEXT DEFAULT '',
            source TEXT DEFAULT '',
            primary_country TEXT DEFAULT '',
            all_countries TEXT DEFAULT '',
            themes TEXT DEFAULT '',
            url TEXT DEFAULT '',
            UNIQUE(report_id, chunk_index)
        );
    """)

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_report_id ON chunks(report_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_primary_country ON chunks(primary_country);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_date ON chunks(date);")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
        USING hnsw (embedding vector_cosine_ops);
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reports_countries ON reports USING gin (countries);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reports_themes ON reports USING gin (themes);")

    conn.commit()
    cur.close()
    conn.close()
    print("Schema created successfully!")


def migrate_reports(reports: List[Dict], supabase_url: str, supabase_key: str, dry_run: bool = False) -> int:
    """Migrate reports to Supabase using REST API."""
    from supabase import create_client, Client

    client: Client = create_client(supabase_url, supabase_key)

    migrated = 0
    skipped = 0
    batch_size = 100

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
                "date": r.get("date", "")[:10] if r.get("date") else None,
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
                "ingested_at": r.get("ingested_at", ""),
            })

        if dry_run:
            print(f"  [DRY RUN] Would insert {len(rows)} reports (batch {i // batch_size + 1})")
            migrated += len(rows)
        else:
            try:
                result = client.table("reports").upsert(rows, on_conflict="report_id").execute()
                migrated += len(rows)
                print(f"  Inserted {len(rows)} reports (batch {i // batch_size + 1})")
            except Exception as e:
                print(f"  Error inserting batch: {e}")
                skipped += len(rows)

    print(f"Reports: {migrated} migrated, {skipped} skipped")
    return migrated


def migrate_chunks_with_embeddings(
    chroma_chunks: List[Dict],
    db_url: str,
    dry_run: bool = False,
) -> int:
    """Migrate chunks with embeddings to Supabase using direct PostgreSQL connection."""
    import psycopg2

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    migrated = 0
    batch_size = 100

    for i in range(0, len(chroma_chunks), batch_size):
        batch = chroma_chunks[i:i + batch_size]

        if dry_run:
            print(f"  [DRY RUN] Would insert {len(batch)} chunks (batch {i // batch_size + 1})")
            migrated += len(batch)
            continue

        for chunk in batch:
            meta = chunk["metadata"]
            emb = chunk["embedding"]
            emb_str = "[" + ",".join(str(x) for x in emb) + "]" if emb else None

            try:
                cur.execute("""
                    INSERT INTO chunks
                        (report_id, chunk_index, source_type, content, char_count,
                         embedding, title, date, source, primary_country,
                         all_countries, themes, url)
                    VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (report_id, chunk_index) DO NOTHING
                """, (
                    meta.get("report_id"),
                    meta.get("chunk_index", 0),
                    meta.get("source_type", "html"),
                    chunk["document"] or "",
                    len(chunk["document"] or ""),
                    emb_str,
                    meta.get("title", ""),
                    meta.get("date", ""),
                    meta.get("source", ""),
                    meta.get("primary_country", ""),
                    meta.get("all_countries", ""),
                    meta.get("themes", ""),
                    meta.get("url", ""),
                ))
                migrated += 1
            except Exception as e:
                print(f"  Error inserting chunk {chunk['id']}: {e}")

        conn.commit()
        print(f"  Inserted {migrated}/{len(chroma_chunks)} chunks...")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Chunks: {migrated} migrated")
    return migrated


def verify_migration(db_url: str, sqlite_path: str, chroma_dir: str, collection_name: str):
    """Verify migration by comparing counts."""
    import psycopg2
    import sqlite3
    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    # PostgreSQL counts
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reports;")
    pg_reports = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM chunks;")
    pg_chunks = cur.fetchone()[0]
    cur.close()
    conn.close()

    # SQLite counts
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_reports = sqlite_conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    sqlite_chunks = sqlite_conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    sqlite_conn.close()

    # ChromaDB counts
    client = chromadb.PersistentClient(path=chroma_dir)
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=DefaultEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )
    chroma_chunks = collection.count()

    print("\n=== Migration Verification ===")
    print(f"  Reports:  SQLite={sqlite_reports}, Supabase={pg_reports}, Match={'✅' if sqlite_reports == pg_reports else '❌'}")
    print(f"  Chunks:   SQLite={sqlite_chunks}, ChromaDB={chroma_chunks}, Supabase={pg_chunks}")
    print(f"  Embeddings: ChromaDB={chroma_chunks}, Supabase={pg_chunks}, Match={'✅' if chroma_chunks == pg_chunks else '❌'}")


def main():
    parser = argparse.ArgumentParser(description="Migrate data from SQLite+ChromaDB to Supabase+pgvector")
    parser.add_argument("--dry-run", action="store_true", help="Don't write anything, just show what would be done")
    parser.add_argument("--reports-only", action="store_true", help="Only migrate reports, skip chunks")
    parser.add_argument("--with-embeddings", action="store_true", help="Migrate chunks with embeddings from ChromaDB")
    parser.add_argument("--skip-reports", action="store_true", help="Skip report migration")
    parser.add_argument("--verify-only", action="store_true", help="Only verify migration, don't migrate")
    parser.add_argument("--db-path", default=str(DB_PATH), help="Path to SQLite database")
    parser.add_argument("--chroma-dir", default=CHROMA_DIR, help="Path to ChromaDB directory")
    args = parser.parse_args()

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")
    db_url = os.getenv("SUPABASE_DB_URL", "")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        print("  export SUPABASE_URL='https://your-project.supabase.co'")
        print("  export SUPABASE_SERVICE_KEY='your-service-key'")
        sys.exit(1)

    if args.with_embeddings and not db_url:
        print("ERROR: SUPABASE_DB_URL must be set for embedding migration")
        print("  export SUPABASE_DB_URL='postgresql://postgres.ref:password@host:5432/postgres'")
        sys.exit(1)

    print("=" * 60)
    print("ReliefWeb → Supabase Migration")
    print("=" * 60)

    if args.dry_run:
        print("  [DRY RUN MODE — no data will be written]")

    # Step 1: Create schema
    if not args.dry_run and db_url:
        print("\nStep 1: Creating Supabase schema...")
        create_supabase_schema(db_url)

    # Step 2: Migrate reports
    if not args.skip_reports and not args.verify_only:
        print("\nStep 2: Migrating reports from SQLite...")
        reports = get_sqlite_reports(args.db_path)
        print(f"  Found {len(reports)} reports in SQLite")
        migrate_reports(reports, supabase_url, supabase_key, dry_run=args.dry_run)

    # Step 3: Migrate chunks with embeddings
    if args.with_embeddings and not args.verify_only:
        if not db_url:
            print("ERROR: SUPABASE_DB_URL required for embedding migration")
            sys.exit(1)

        print("\nStep 3: Migrating chunks with embeddings from ChromaDB...")
        chroma_chunks = get_chromadb_chunks_with_embeddings(args.chroma_dir, CHROMA_COLLECTION)
        print(f"  Found {len(chroma_chunks)} chunks in ChromaDB")
        migrate_chunks_with_embeddings(chroma_chunks, db_url, dry_run=args.dry_run)

    # Step 4: Verify
    if db_url:
        print("\nStep 4: Verifying migration...")
        verify_migration(db_url, args.db_path, args.chroma_dir, CHROMA_COLLECTION)

    print("\n✅ Migration complete!")


if __name__ == "__main__":
    main()