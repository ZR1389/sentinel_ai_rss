-- Enhanced Database Index Optimization for Sentinel AI
-- This script ensures all database operations are properly indexed for optimal performance

-- ====================================================================================
-- DATABASE INDEX OPTIMIZATION SCRIPT
-- ====================================================================================

-- Drop existing indexes that might be redundant or suboptimal
-- (Only if they exist - PostgreSQL will ignore if they don't exist)

-- ====================================================================================
-- PRIMARY TABLES: ALERTS & RAW_ALERTS
-- ====================================================================================

-- 1. ALERTS TABLE INDEXES
-- Core performance indexes for the main alerts table

-- UUID index for primary key operations (already exists as unique constraint)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_uuid_btree ON alerts USING btree (uuid);

-- Published timestamp - critical for time-based queries  
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_published_desc ON alerts USING btree (published DESC NULLS LAST);

-- Composite index for geographic queries (most common query pattern)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_geo_published ON alerts USING btree (country, city, region, published DESC NULLS LAST);

-- Category-based queries with time ordering
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_category_published ON alerts USING btree (category, published DESC NULLS LAST);

-- Threat level queries 
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_threat_published ON alerts USING btree (threat_level, published DESC NULLS LAST);

-- Score-based filtering and sorting
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_score_published ON alerts USING btree (score DESC, published DESC NULLS LAST);

-- Ingested timestamp for data pipeline queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_ingested_at_desc ON alerts USING btree (ingested_at DESC NULLS LAST);

-- Geographic coordinates for spatial queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_coords ON alerts USING btree (latitude, longitude) WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Composite index for chat/advisor queries (optimized for fetch_alerts_from_db_strict_geo)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_chat_queries ON alerts USING btree (country, city, category, published DESC NULLS LAST) WHERE country IS NOT NULL;

-- Review flag for administrative queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_review_flag ON alerts USING btree (review_flag, ingested_at DESC) WHERE review_flag = true;

-- Anomaly detection queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_anomaly_published ON alerts USING btree (anomaly_flag, is_anomaly, published DESC NULLS LAST) WHERE anomaly_flag = true OR is_anomaly = true;

-- Series and cluster analysis
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_series_id ON alerts USING btree (series_id, published DESC NULLS LAST) WHERE series_id IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_cluster_id ON alerts USING btree (cluster_id) WHERE cluster_id IS NOT NULL;

-- JSONB indexes for complex queries
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_tags_gin ON alerts USING gin (tags) WHERE tags IS NOT NULL AND array_length(tags, 1) > 0;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_domains_gin ON alerts USING gin (domains) WHERE domains IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_sources_gin ON alerts USING gin (sources) WHERE sources IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_early_warnings_gin ON alerts USING gin (early_warning_indicators) WHERE early_warning_indicators IS NOT NULL AND array_length(early_warning_indicators, 1) > 0;

-- Text search indexes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_title_trgm ON alerts USING gin (title gin_trgm_ops) WHERE title IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_summary_trgm ON alerts USING gin (summary gin_trgm_ops) WHERE summary IS NOT NULL;

-- Multi-column indexes for common filter combinations
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_region_category_time ON alerts USING btree (region, category, published DESC NULLS LAST) WHERE region IS NOT NULL;

-- 2. RAW_ALERTS TABLE INDEXES  
-- Indexes for the raw data ingestion table

-- UUID for conflict resolution during ingestion
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_uuid_btree ON raw_alerts USING btree (uuid);

-- Ingestion tracking
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_ingested_desc ON raw_alerts USING btree (ingested_at DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_published_desc ON raw_alerts USING btree (published DESC NULLS LAST);

-- Geographic processing
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_geo_composite ON raw_alerts USING btree (country, city, region, published DESC NULLS LAST);

-- Source tracking for data quality
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_source_priority ON raw_alerts USING btree (source, source_priority DESC NULLS LAST, ingested_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_source_tag ON raw_alerts USING btree (source_tag, ingested_at DESC) WHERE source_tag IS NOT NULL;

-- Location processing status
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_location_method ON raw_alerts USING btree (location_method, location_confidence) WHERE location_method IS NOT NULL;

-- JSONB index for tags processing
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_tags_gin ON raw_alerts USING gin (tags) WHERE tags IS NOT NULL;

-- Processing queue optimization (unprocessed alerts)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_processing_queue ON raw_alerts USING btree (ingested_at DESC) 
WHERE NOT EXISTS (SELECT 1 FROM alerts WHERE alerts.uuid = raw_alerts.uuid);

-- ====================================================================================  
-- SUPPORTING TABLES INDEXES
-- ====================================================================================

-- 3. USERS TABLE INDEXES
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email_hash ON users USING hash (email);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_plan_active ON users USING btree (plan, is_active) WHERE is_active = true;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email_verified ON users USING btree (email_verified, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_preferred_region ON users USING btree (preferred_region) WHERE preferred_region IS NOT NULL;

-- 4. USER_USAGE TABLE INDEXES  
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_usage_email ON user_usage USING btree (email);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_user_usage_reset_due ON user_usage USING btree (last_reset) WHERE last_reset < NOW() - INTERVAL '1 month';

-- 5. SECURITY_EVENTS TABLE INDEXES
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_security_events_type_time ON security_events USING btree (event_type, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_security_events_email_time ON security_events USING btree (email, created_at DESC) WHERE email IS NOT NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_security_events_ip_time ON security_events USING btree (ip_address, created_at DESC) WHERE ip_address IS NOT NULL;

-- 6. EMAIL_ALERTS TABLE INDEXES
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_alerts_email_status ON email_alerts USING btree (email, status, sent_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_alerts_alert_id ON email_alerts USING btree (alert_id);

-- 7. REGION_TRENDS TABLE INDEXES
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_region_trends_window ON region_trends USING btree (region, city, window_start DESC, window_end DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_region_trends_incident_count ON region_trends USING btree (incident_count DESC, window_start DESC);

-- 8. REFRESH_TOKENS TABLE INDEXES  
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_refresh_tokens_email_expires ON refresh_tokens USING btree (email, expires_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_refresh_tokens_cleanup ON refresh_tokens USING btree (expires_at) WHERE expires_at < NOW();

-- 9. EMAIL_VERIFICATION TABLES INDEXES
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_verification_codes_email ON email_verification_codes USING btree (email, expires_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_email_verification_ip_log_ip_time ON email_verification_ip_log USING btree (ip, ts DESC);

-- ====================================================================================
-- SPECIALIZED INDEXES FOR ADVANCED FEATURES
-- ====================================================================================

-- 10. VECTOR/EMBEDDING SUPPORT
-- If using pgvector extension for semantic search
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_embedding_cosine ON alerts USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100) WHERE embedding IS NOT NULL;

-- 11. FULL-TEXT SEARCH INDEXES
-- Enable trigram extension for fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Full-text search on title and summary
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_fulltext ON alerts USING gin (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(summary, '')));
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_alerts_fulltext ON raw_alerts USING gin (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(summary, '')));

-- ====================================================================================
-- PERFORMANCE MONITORING VIEWS  
-- ====================================================================================

-- Create a view for monitoring slow queries
CREATE OR REPLACE VIEW db_performance_monitor AS
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_tup_read,
    idx_tup_fetch,
    idx_scan AS index_scans,
    seq_scan AS sequential_scans,
    CASE 
        WHEN seq_scan = 0 THEN 0 
        ELSE ROUND((seq_scan::float / (seq_scan + idx_scan)) * 100, 2) 
    END AS seq_scan_percentage
FROM pg_stat_user_indexes
ORDER BY seq_scan DESC, idx_scan DESC;

-- Create a view for monitoring table statistics
CREATE OR REPLACE VIEW table_performance_monitor AS  
SELECT 
    schemaname,
    tablename,
    n_tup_ins AS inserts,
    n_tup_upd AS updates,
    n_tup_del AS deletes,
    n_live_tup AS live_rows,
    n_dead_tup AS dead_rows,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    CASE 
        WHEN n_live_tup = 0 THEN 0 
        ELSE ROUND((n_dead_tup::float / n_live_tup) * 100, 2) 
    END AS dead_row_percentage
FROM pg_stat_user_tables
ORDER BY dead_row_percentage DESC, n_live_tup DESC;

-- ====================================================================================
-- INDEX MAINTENANCE UTILITIES
-- ====================================================================================

-- Function to get index usage statistics
CREATE OR REPLACE FUNCTION get_index_usage_stats()
RETURNS TABLE (
    schema_name text,
    table_name text,
    index_name text,
    index_size text,
    index_scans bigint,
    sequential_scans bigint,
    efficiency_rating text
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        psi.schemaname::text,
        psi.tablename::text,
        psi.indexname::text,
        pg_size_pretty(pg_relation_size(psi.indexrelid))::text,
        psi.idx_scan,
        pst.seq_scan,
        CASE 
            WHEN psi.idx_scan = 0 AND pst.seq_scan > 100 THEN 'UNUSED - Consider dropping'
            WHEN psi.idx_scan < 10 AND pst.seq_scan > 1000 THEN 'LOW USAGE'
            WHEN psi.idx_scan > 1000 AND pst.seq_scan < 100 THEN 'HIGH EFFICIENCY'
            ELSE 'NORMAL'
        END::text
    FROM pg_stat_user_indexes psi
    JOIN pg_stat_user_tables pst ON psi.schemaname = pst.schemaname AND psi.tablename = pst.tablename
    WHERE psi.schemaname = 'public'
    ORDER BY psi.idx_scan DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to identify missing indexes based on query patterns
CREATE OR REPLACE FUNCTION suggest_missing_indexes()
RETURNS TABLE (
    suggestion_type text,
    table_name text,
    recommended_index text,
    reasoning text
) AS $$
BEGIN
    RETURN QUERY
    -- High sequential scan tables that might benefit from indexes
    SELECT 
        'HIGH_SEQ_SCAN'::text,
        pst.tablename::text,
        'CREATE INDEX idx_' || pst.tablename || '_analyze ON ' || pst.tablename || ' (...);'::text,
        'Table has ' || pst.seq_scan || ' sequential scans with only ' || COALESCE(psi.idx_scan, 0) || ' index scans'::text
    FROM pg_stat_user_tables pst
    LEFT JOIN pg_stat_user_indexes psi ON pst.schemaname = psi.schemaname AND pst.tablename = psi.tablename
    WHERE pst.seq_scan > 1000 
      AND (psi.idx_scan IS NULL OR psi.idx_scan < 100)
      AND pst.schemaname = 'public'
    
    UNION ALL
    
    -- Large tables without proper indexes
    SELECT 
        'LARGE_TABLE'::text,
        pst.tablename::text,
        'CREATE INDEX idx_' || pst.tablename || '_composite ON ' || pst.tablename || ' (...);'::text,
        'Large table (' || pst.n_live_tup || ' rows) may benefit from additional indexes'::text
    FROM pg_stat_user_tables pst
    WHERE pst.n_live_tup > 10000
      AND pst.schemaname = 'public'
      AND NOT EXISTS (
          SELECT 1 FROM pg_stat_user_indexes psi 
          WHERE psi.schemaname = pst.schemaname 
            AND psi.tablename = pst.tablename 
            AND psi.idx_scan > 100
      );
END;
$$ LANGUAGE plpgsql;

-- ====================================================================================
-- MAINTENANCE TASKS
-- ====================================================================================

-- Update table statistics for the query planner
ANALYZE;

-- Log completion
SELECT 'Database index optimization completed at ' || now() AS status;

-- ====================================================================================
-- INDEX VALIDATION QUERIES
-- ====================================================================================

-- Verify critical indexes exist
SELECT 'Checking critical indexes...' AS status;

-- Check that primary performance indexes exist
SELECT 
    i.indexname,
    CASE WHEN i.indexname IS NOT NULL THEN 'EXISTS' ELSE 'MISSING' END as status
FROM (VALUES 
    ('idx_alerts_published_desc'),
    ('idx_alerts_geo_published'), 
    ('idx_alerts_category_published'),
    ('idx_raw_alerts_ingested_desc'),
    ('idx_users_email_hash')
) AS expected(indexname)
LEFT JOIN pg_indexes i ON i.indexname = expected.indexname
ORDER BY expected.indexname;

-- Show index sizes
SELECT 
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes 
WHERE schemaname = 'public'
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 20;
