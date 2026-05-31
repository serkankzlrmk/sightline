-- ============================================================================
-- ReliefWeb Agent — Supabase Schema Setup
-- ============================================================================
-- Run this in the Supabase SQL Editor to set up the database.
--
-- Prerequisites:
--   1. Create a new Supabase project at https://supabase.com
--   2. Enable the pgvector extension (included below)
--   3. Run this entire script in the SQL Editor
--   4. Copy the connection details to your .env file
--
-- Environment variables needed:
--   SUPABASE_URL=https://your-project.supabase.co
--   SUPABASE_ANON_KEY=your-anon-key
--   SUPABASE_SERVICE_KEY=your-service-key
--   SUPABASE_DB_URL=postgresql://postgres.your-ref:password@aws-0-region.pooler.supabase.com:6543/postgres
--   VECTOR_BACKEND=pgvector
-- ============================================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- REPORTS TABLE
-- ============================================================================
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

-- ============================================================================
-- CHUNKS TABLE (with pgvector embedding column)
-- ============================================================================
CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    report_id INTEGER REFERENCES reports(report_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    source_type TEXT DEFAULT 'html',
    content TEXT NOT NULL,
    char_count INTEGER DEFAULT 0,
    embedding vector(384),  -- all-MiniLM-L6-v2 dimension
    title TEXT DEFAULT '',
    date TEXT DEFAULT '',
    source TEXT DEFAULT '',
    primary_country TEXT DEFAULT '',
    all_countries TEXT DEFAULT '',
    themes TEXT DEFAULT '',
    url TEXT DEFAULT '',
    UNIQUE(report_id, chunk_index)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Fast lookups by report_id
CREATE INDEX IF NOT EXISTS idx_chunks_report_id ON chunks(report_id);

-- Fast lookups by primary_country
CREATE INDEX IF NOT EXISTS idx_chunks_primary_country ON chunks(primary_country);

-- Fast lookups by date
CREATE INDEX IF NOT EXISTS idx_chunks_date ON chunks(date);

-- HNSW index for vector similarity search (cosine distance)
-- This is the key index for fast semantic search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops);

-- GIN indexes for JSONB queries (countries, themes)
CREATE INDEX IF NOT EXISTS idx_reports_countries ON reports USING gin (countries);
CREATE INDEX IF NOT EXISTS idx_reports_themes ON reports USING gin (themes);

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================================
-- Enable RLS but allow full access via service key

ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;

-- Service key can do everything
CREATE POLICY "Service key full access on reports" ON reports
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

CREATE POLICY "Service key full access on chunks" ON chunks
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Anon key can read (for search queries)
CREATE POLICY "Anon key read access on reports" ON reports
    FOR SELECT USING (true);

CREATE POLICY "Anon key read access on chunks" ON chunks
    FOR SELECT USING (true);

-- ============================================================================
-- REALTIME (optional — enable if you want live updates)
-- ============================================================================
ALTER PUBLICATION supabase_realtime ADD TABLE reports;
ALTER PUBLICATION supabase_realtime ADD TABLE chunks;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to search chunks by vector similarity
CREATE OR REPLACE FUNCTION search_chunks(
    query_embedding vector(384),
    match_count int DEFAULT 10,
    filter_country text DEFAULT NULL
)
RETURNS TABLE (
    id int,
    report_id int,
    chunk_index int,
    source_type text,
    content text,
    char_count int,
    title text,
    date text,
    source text,
    primary_country text,
    all_countries text,
    themes text,
    url text,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id,
        c.report_id,
        c.chunk_index,
        c.source_type,
        c.content,
        c.char_count,
        c.title,
        c.date,
        c.source,
        c.primary_country,
        c.all_countries,
        c.themes,
        c.url,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM chunks c
    WHERE filter_country IS NULL OR c.primary_country = filter_country
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Function to list distinct countries
CREATE OR REPLACE FUNCTION list_countries()
RETURNS TABLE (country text)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT primary_country AS country
    FROM chunks
    WHERE primary_country IS NOT NULL AND primary_country != ''
    ORDER BY primary_country;
END;
$$;

-- Function to list distinct themes
CREATE OR REPLACE FUNCTION list_themes()
RETURNS TABLE (theme text)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT unnest(string_to_array(themes, ',')) AS theme
    FROM chunks
    WHERE themes IS NOT NULL AND themes != ''
    ORDER BY theme;
END;
$$;

-- Function to get date range for a country
CREATE OR REPLACE FUNCTION get_date_range(country_name text)
RETURNS TABLE (min_date text, max_date text, count int)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        MIN(c.date)::text AS min_date,
        MAX(c.date)::text AS max_date,
        COUNT(*)::int AS count
    FROM chunks c
    WHERE c.primary_country = country_name
      AND c.date IS NOT NULL AND c.date != '';
END;
$$;

-- ============================================================================
-- VERIFICATION
-- ============================================================================
-- Run these queries to verify setup:
-- SELECT * FROM reports LIMIT 5;
-- SELECT count(*) FROM chunks;
-- SELECT list_countries();
-- SELECT get_date_range('Lebanon');