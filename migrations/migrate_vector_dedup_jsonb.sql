-- Simplified vector deduplication migration (without pgvector extension)
-- This version stores embeddings as JSON and provides basic functionality
-- Can be upgraded to pgvector when extension is available

-- Add embedding column as JSONB (fallback for systems without pgvector)
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS embedding_json JSONB;

-- Add similarity threshold column for caching duplicate checks
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS similarity_checked_at TIMESTAMP;

-- Create index on embedding_json for faster queries
CREATE INDEX IF NOT EXISTS idx_alerts_embedding_json ON alerts USING gin(embedding_json);

-- Function to calculate cosine similarity between JSONB arrays
CREATE OR REPLACE FUNCTION cosine_similarity(a JSONB, b JSONB) RETURNS FLOAT AS $$
DECLARE
    dot_product FLOAT := 0;
    norm_a FLOAT := 0;
    norm_b FLOAT := 0;
    i INTEGER;
    val_a FLOAT;
    val_b FLOAT;
BEGIN
    -- Check if inputs are valid arrays
    IF jsonb_typeof(a) != 'array' OR jsonb_typeof(b) != 'array' THEN
        RETURN 0;
    END IF;
    
    -- Check if arrays have same length
    IF jsonb_array_length(a) != jsonb_array_length(b) THEN
        RETURN 0;
    END IF;
    
    -- Calculate dot product and norms
    FOR i IN 0..jsonb_array_length(a)-1 LOOP
        val_a := (a->>i)::FLOAT;
        val_b := (b->>i)::FLOAT;
        
        dot_product := dot_product + (val_a * val_b);
        norm_a := norm_a + (val_a * val_a);
        norm_b := norm_b + (val_b * val_b);
    END LOOP;
    
    -- Avoid division by zero
    IF norm_a = 0 OR norm_b = 0 THEN
        RETURN 0;
    END IF;
    
    RETURN dot_product / (sqrt(norm_a) * sqrt(norm_b));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Function to find similar alerts using JSONB embeddings
CREATE OR REPLACE FUNCTION find_similar_alerts_jsonb(
    query_embedding JSONB,
    similarity_threshold FLOAT DEFAULT 0.92,
    max_results INTEGER DEFAULT 5
) RETURNS TABLE(alert_uuid TEXT, similarity FLOAT, title TEXT) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.uuid::text,
        cosine_similarity(a.embedding_json, query_embedding) as sim,
        a.title
    FROM alerts a
    WHERE a.embedding_json IS NOT NULL
    AND cosine_similarity(a.embedding_json, query_embedding) > similarity_threshold
    ORDER BY cosine_similarity(a.embedding_json, query_embedding) DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Function to check if an alert is a duplicate
CREATE OR REPLACE FUNCTION check_duplicate_alert_jsonb(
    alert_title TEXT,
    alert_summary TEXT,
    query_embedding JSONB,
    similarity_threshold FLOAT DEFAULT 0.92
) RETURNS BOOLEAN AS $$
DECLARE
    similar_count INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO similar_count
    FROM find_similar_alerts_jsonb(query_embedding, similarity_threshold, 1);
    
    RETURN similar_count > 0;
END;
$$ LANGUAGE plpgsql;

-- Add column to track deduplication method used
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS dedup_method VARCHAR(20) DEFAULT 'hash';

-- Create composite index for efficient similarity searches
CREATE INDEX IF NOT EXISTS idx_alerts_embedding_similarity 
ON alerts (dedup_method, similarity_checked_at) 
WHERE embedding_json IS NOT NULL;

-- Update statistics
ANALYZE alerts;

SELECT 'Simplified vector deduplication migration completed (JSONB fallback)' as status;
