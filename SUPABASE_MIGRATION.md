# Supabase + pgvector Migration Guide

This guide explains how to migrate from local SQLite + ChromaDB to Supabase + pgvector.

## Why Migrate?

- **Hardware relief**: ChromaDB runs locally and uses significant RAM/CPU. Moving to Supabase offloads vector storage and search to the cloud.
- **Scalability**: Supabase's PostgreSQL + pgvector handles larger datasets more efficiently.
- **Reliability**: Cloud-hosted database with automatic backups and high availability.
- **Free tier**: Supabase offers 500MB PostgreSQL + 2 pgvector indexes on the free plan.

## Architecture

```
BEFORE (current):
  SQLite (metadata) + ChromaDB (vectors) → all on local server

AFTER (migrated):
  Supabase PostgreSQL (metadata + vectors) → cloud-hosted
  Local server only runs the Flask app + LLM calls
```

## Setup Steps

### 1. Create a Supabase Project

1. Go to [https://supabase.com](https://supabase.com) and create a free account
2. Create a new project (choose a region close to your users)
3. Wait for the project to be provisioned (~2 minutes)

### 2. Set Up Database Schema

1. Go to **SQL Editor** in your Supabase dashboard
2. Copy the contents of `supabase_schema.sql` and run it
3. This creates:
   - `reports` table (metadata)
   - `chunks` table (with pgvector embedding column)
   - HNSW index for fast vector search
   - GIN indexes for JSONB queries
   - Helper functions for common queries
   - Row Level Security policies

### 3. Get Connection Details

From your Supabase dashboard → **Settings** → **API**:
- `SUPABASE_URL`: Project URL (e.g., `https://abc123.supabase.co`)
- `SUPABASE_ANON_KEY`: Public anon key
- `SUPABASE_SERVICE_KEY`: Secret service key (for admin access)

From **Settings** → **Database** → **Connection string**:
- `SUPABASE_DB_URL`: PostgreSQL connection string
  - Use the **Transaction pooler** connection (port 6543) for direct SQL
  - Format: `postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`

### 4. Configure Environment Variables

Add to your `.env` file (or production environment):

```bash
VECTOR_BACKEND=pgvector
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-key
SUPABASE_DB_URL=postgresql://postgres.ref:password@aws-0-region.pooler.supabase.com:6543/postgres
EMBEDDING_DIM=384
```

### 5. Migrate Data

Run the migration script:

```bash
# Dry run first (no writes):
python migrate_to_supabase.py --dry-run

# Migrate reports only:
python migrate_to_supabase.py --reports-only

# Full migration (reports + chunks with embeddings):
python migrate_to_supabase.py --with-embeddings

# Verify migration:
python migrate_to_supabase.py --verify-only
```

**Note**: The `--with-embeddings` flag reads all chunks from ChromaDB (including embeddings) and inserts them into Supabase. This can take 30-60 minutes for ~25,000 chunks.

### 6. Switch Backend

Set `VECTOR_BACKEND=pgvector` in your environment and restart the server.

The app will automatically:
- Use `PgVectorStore` instead of `ChromaDB` for vector operations
- Use `SupabaseDB` for metadata queries (when configured)
- Fall back to SQLite for queries if Supabase is unavailable

### 7. Verify

1. Check health endpoint: `GET /api/health` — should show `vector_backend: pgvector`
2. Test SITREP endpoints:
   - `GET /api/sitrep/countries` — should return country list
   - `GET /api/sitrep/themes` — should return theme list
   - `POST /api/sitrep/run` — should work end-to-end

## Switching Back

To switch back to ChromaDB, simply set:

```bash
VECTOR_BACKEND=chromadb
```

And restart the server. No data loss — both backends can coexist.

## Cost Estimate

- **Supabase Free Tier**: 500MB PostgreSQL, 2 pgvector indexes, 50K monthly active users
- **Expected usage**: ~25K chunks × 384 dimensions × 4 bytes = ~38MB vector data + ~50MB text = ~88MB total
- **Free tier is sufficient** for the current dataset

## Files Changed

| File | Change |
|------|--------|
| `config.py` | Added `VECTOR_BACKEND`, `SUPABASE_URL/KEY/DB_URL`, `EMBEDDING_DIM` |
| `reliefweb_api/pgvector_store.py` | **NEW** — PgVectorStore class |
| `reliefweb_api/supabase_db.py` | **NEW** — SupabaseDB class |
| `reliefweb_api/vector_store.py` | Updated to support both backends |
| `sitrep/chroma_adapter.py` | Updated to support both backends |
| `reliefweb_api/ingest_pipeline.py` | Updated to use VECTOR_BACKEND config |
| `server.py` | Updated health check for pgvector |
| `requirements.txt` | Added `supabase`, `psycopg2-binary` |
| `migrate_to_supabase.py` | **NEW** — Migration script |
| `supabase_schema.sql` | **NEW** — Database schema |
| `.env.example` | Added Supabase configuration |