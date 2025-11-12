-- Vector Database Deduplication Migration
-- Replaces O(N²) semantic deduplication with efficient pgvector similarity search
-- Date: 2025-01-11

-- Step 1: Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Step 2: Add embedding column to alerts table
-- Using 1536 dimensions for OpenAI text-embedding-3-small
-- Using 384 dimensions for sentence-transformers models (more efficient alternative)
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- Add index for the embedding column after data population
-- Note: This will be created after embeddings are populated to avoid performance issues

-- Step 3: Create optimized similarity search function
CREATE OR REPLACE FUNCTION find_similar_alerts(
    query_embedding vector(1536),
    similarity_threshold float DEFAULT 0.92,
    max_results integer DEFAULT 5
) RETURNS TABLE(alert_uuid text, similarity float, title text) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        uuid::text, 
        1 - (embedding <=> query_embedding) as similarity,
        alerts.title
    FROM alerts 
    WHERE embedding IS NOT NULL
    AND 1 - (embedding <=> query_embedding) > similarity_threshold
    ORDER BY embedding <=> query_embedding
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Step 4: Create function to check for duplicates before insert
CREATE OR REPLACE FUNCTION check_duplicate_alert(
    query_embedding vector(1536),
    similarity_threshold float DEFAULT 0.92
) RETURNS boolean AS $$
DECLARE
    similar_count integer;
BEGIN
    SELECT COUNT(*) INTO similar_count
    FROM alerts 
    WHERE embedding IS NOT NULL
    AND 1 - (embedding <=> query_embedding) > similarity_threshold
    LIMIT 1;
    
    RETURN similar_count > 0;
END;
$$ LANGUAGE plpgsql;

-- Step 5: Create batch similarity search for deduplication
CREATE OR REPLACE FUNCTION batch_find_duplicates(
    embeddings_json jsonb,
    similarity_threshold float DEFAULT 0.92
) RETURNS TABLE(embedding_index integer, duplicate_uuid text, similarity float) AS $$
DECLARE
    embedding_item jsonb;
    embedding_index integer := 0;
    query_embedding vector(1536);
BEGIN
    FOR embedding_item IN SELECT jsonb_array_elements(embeddings_json)
    LOOP
        -- Convert JSON array to vector
        query_embedding := embedding_item->>'embedding';
        
        -- Find duplicates for this embedding
        RETURN QUERY
        SELECT 
            embedding_index,
            uuid::text, 
            1 - (embedding <=> query_embedding) as similarity
        FROM alerts 
        WHERE embedding IS NOT NULL
        AND 1 - (embedding <=> query_embedding) > similarity_threshold
        ORDER BY embedding <=> query_embedding
        LIMIT 1;  -- Only return best match per input
        
        embedding_index := embedding_index + 1;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Step 6: Create indexes for performance (run after embedding population)
-- This is commented out initially - will be created by the application after data migration

-- CREATE INDEX CONCURRENTLY idx_alerts_embedding_ivfflat 
-- ON alerts USING ivfflat (embedding vector_cosine_ops) 
-- WITH (lists = 100);

-- Alternative: HNSW index (better for smaller datasets, faster queries)
-- CREATE INDEX CONCURRENTLY idx_alerts_embedding_hnsw 
-- ON alerts USING hnsw (embedding vector_cosine_ops) 
-- WITH (m = 16, ef_construction = 64);

-- Step 7: Create function to populate embeddings for existing alerts
CREATE OR REPLACE FUNCTION populate_alert_embeddings()
RETURNS integer AS $$
DECLARE
    alert_count integer := 0;
BEGIN
    -- This will be called from the application with actual embeddings
    -- Placeholder function for manual embedding population
    RAISE NOTICE 'Use application code to populate embeddings with get_embedding()';
    RETURN 0;
END;
$$ LANGUAGE plpgsql;

-- Step 8: Add monitoring views
CREATE OR REPLACE VIEW alert_embedding_stats AS
SELECT 
    COUNT(*) as total_alerts,
    COUNT(embedding) as alerts_with_embeddings,
    ROUND(100.0 * COUNT(embedding) / NULLIF(COUNT(*), 0), 2) as embedding_coverage_pct,
    MIN(created_at) as oldest_alert,
    MAX(created_at) as newest_alert
FROM alerts;

-- Step 9: Create utility function to get embedding dimension info
CREATE OR REPLACE FUNCTION get_embedding_info()
RETURNS TABLE(
    total_alerts bigint,
    alerts_with_embeddings bigint,
    coverage_percentage numeric,
    avg_embedding_size integer
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*) as total_alerts,
        COUNT(embedding) as alerts_with_embeddings,
        ROUND(100.0 * COUNT(embedding) / NULLIF(COUNT(*), 0), 2) as coverage_percentage,
        CASE 
            WHEN COUNT(embedding) > 0 THEN 1536 
            ELSE 0 
        END as avg_embedding_size
    FROM alerts;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON COLUMN alerts.embedding IS 'OpenAI text-embedding-3-small vector (1536 dimensions) for semantic similarity search';
COMMENT ON FUNCTION find_similar_alerts IS 'Find semantically similar alerts using cosine similarity';
COMMENT ON FUNCTION check_duplicate_alert IS 'Check if an alert is a duplicate based on embedding similarity';
COMMENT ON FUNCTION batch_find_duplicates IS 'Batch process multiple embeddings to find duplicates efficiently';

-- Performance notes:
-- 1. ivfflat index: Better for larger datasets, requires training with lists parameter
-- 2. hnsw index: Better for smaller datasets (<1M vectors), faster queries
-- 3. Cosine distance (<=> operator) is preferred for normalized embeddings
-- 4. L2 distance (<-> operator) can be used for non-normalized embeddings

-- Migration complete
SELECT 'Vector database deduplication migration completed' as status;
