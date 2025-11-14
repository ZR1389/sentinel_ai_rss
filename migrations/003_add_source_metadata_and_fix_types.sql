-- Migration 003: Add source metadata to alerts table and fix data types
-- This migration:
-- 1. Adds source_kind and source_tag columns to alerts table
-- 2. Fixes score/confidence/future_risk_probability types from TEXT to NUMERIC
-- 3. Adds threat_score_components JSONB column (may already exist)
-- 4. Creates indexes for better query performance

BEGIN;

-- ============================================================================
-- STEP 1: Add source metadata columns to alerts table
-- ============================================================================

-- Add source_kind column (identifies ACLED vs RSS)
ALTER TABLE alerts 
ADD COLUMN IF NOT EXISTS source_kind TEXT;

-- Add source_tag column (additional categorization like "country:Nigeria")
ALTER TABLE alerts 
ADD COLUMN IF NOT EXISTS source_tag TEXT;

-- Create indexes for filtering by source
CREATE INDEX IF NOT EXISTS idx_alerts_source_kind ON alerts(source_kind);
CREATE INDEX IF NOT EXISTS idx_alerts_source_tag ON alerts(source_tag);

COMMENT ON COLUMN alerts.source_kind IS 'Source type: "intelligence" (ACLED), "rss" (RSS feeds), etc.';
COMMENT ON COLUMN alerts.source_tag IS 'Additional source tagging like "country:Nigeria" or "feed:bbc"';

-- ============================================================================
-- STEP 2: Fix numeric type issues (score, confidence, etc.)
-- ============================================================================

-- Check and fix score column type (should be numeric, not text)
DO $$ 
BEGIN
    -- Only alter if currently TEXT type
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'alerts' 
        AND column_name = 'score' 
        AND data_type IN ('text', 'character varying')
    ) THEN
        -- First, clean any non-numeric values
        UPDATE alerts SET score = '0' WHERE score !~ '^[0-9]+\.?[0-9]*$' OR score IS NULL;
        
        -- Convert to numeric
        ALTER TABLE alerts ALTER COLUMN score TYPE numeric USING score::numeric;
        
        -- Add constraint
        ALTER TABLE alerts ADD CONSTRAINT score_range CHECK (score >= 0 AND score <= 100);
        
        RAISE NOTICE 'Converted alerts.score from TEXT to NUMERIC';
    ELSE
        RAISE NOTICE 'alerts.score is already numeric type';
    END IF;
END $$;

-- Check and fix confidence column type (should be numeric 0-1, not text)
DO $$ 
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'alerts' 
        AND column_name = 'confidence' 
        AND data_type IN ('text', 'character varying')
    ) THEN
        -- Clean non-numeric values
        UPDATE alerts SET confidence = '0.5' WHERE confidence !~ '^[0-9]+\.?[0-9]*$' OR confidence IS NULL;
        
        -- Convert to numeric
        ALTER TABLE alerts ALTER COLUMN confidence TYPE numeric USING confidence::numeric;
        
        -- Add constraint
        ALTER TABLE alerts ADD CONSTRAINT confidence_range CHECK (confidence >= 0 AND confidence <= 1);
        
        RAISE NOTICE 'Converted alerts.confidence from TEXT to NUMERIC';
    ELSE
        RAISE NOTICE 'alerts.confidence is already numeric type';
    END IF;
END $$;

-- Check and fix future_risk_probability column type (should be numeric 0-1, not text)
DO $$ 
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'alerts' 
        AND column_name = 'future_risk_probability' 
        AND data_type IN ('text', 'character varying')
    ) THEN
        -- Clean non-numeric values
        UPDATE alerts SET future_risk_probability = '0.25' 
        WHERE future_risk_probability !~ '^[0-9]+\.?[0-9]*$' OR future_risk_probability IS NULL;
        
        -- Convert to numeric
        ALTER TABLE alerts ALTER COLUMN future_risk_probability TYPE numeric USING future_risk_probability::numeric;
        
        -- Add constraint
        ALTER TABLE alerts ADD CONSTRAINT future_risk_probability_range 
        CHECK (future_risk_probability >= 0 AND future_risk_probability <= 1);
        
        RAISE NOTICE 'Converted alerts.future_risk_probability from TEXT to NUMERIC';
    ELSE
        RAISE NOTICE 'alerts.future_risk_probability is already numeric type';
    END IF;
END $$;

-- ============================================================================
-- STEP 3: Add threat_score_components JSONB column (if not exists)
-- ============================================================================

-- This column stores the SOCMINT scoring breakdown
ALTER TABLE alerts 
ADD COLUMN IF NOT EXISTS threat_score_components JSONB;

-- Create GIN index for JSONB queries
CREATE INDEX IF NOT EXISTS idx_alerts_threat_score_components 
ON alerts USING gin (threat_score_components);

COMMENT ON COLUMN alerts.threat_score_components IS 
'JSONB breakdown of threat scoring factors including SOCMINT contribution: {socmint_raw, socmint_weighted, socmint_weight}';

-- ============================================================================
-- STEP 4: Create performance indexes
-- ============================================================================

-- Index for high-score queries (used in frontend filters)
CREATE INDEX IF NOT EXISTS idx_alerts_score_numeric ON alerts (score) WHERE score > 50;

-- Index for high-confidence queries
CREATE INDEX IF NOT EXISTS idx_alerts_confidence_numeric ON alerts (confidence) WHERE confidence > 0.7;

-- Composite index for common frontend query pattern (source + score + published)
CREATE INDEX IF NOT EXISTS idx_alerts_source_score_published 
ON alerts (source_kind, score DESC, published DESC);

-- Index for SOCMINT-enriched alerts
CREATE INDEX IF NOT EXISTS idx_alerts_has_socmint 
ON alerts ((threat_score_components->>'socmint_raw')) 
WHERE threat_score_components IS NOT NULL;

-- ============================================================================
-- STEP 5: Populate source_kind for existing alerts
-- ============================================================================

-- Backfill source_kind based on UUID pattern for existing ACLED alerts
UPDATE alerts 
SET source_kind = 'intelligence' 
WHERE uuid LIKE 'acled:%' AND source_kind IS NULL;

-- Backfill source_kind for RSS alerts (anything not ACLED)
UPDATE alerts 
SET source_kind = 'rss' 
WHERE uuid NOT LIKE 'acled:%' AND source_kind IS NULL;

-- Log completion statistics
DO $$ 
DECLARE
    acled_count INTEGER;
    rss_count INTEGER;
    total_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO acled_count FROM alerts WHERE source_kind = 'intelligence';
    SELECT COUNT(*) INTO rss_count FROM alerts WHERE source_kind = 'rss';
    SELECT COUNT(*) INTO total_count FROM alerts;
    
    RAISE NOTICE '=== Migration 003 Complete ===';
    RAISE NOTICE 'Total alerts: %', total_count;
    RAISE NOTICE 'ACLED alerts: %', acled_count;
    RAISE NOTICE 'RSS alerts: %', rss_count;
    RAISE NOTICE 'Columns added: source_kind, source_tag, threat_score_components';
    RAISE NOTICE 'Type fixes: score, confidence, future_risk_probability converted to NUMERIC';
END $$;

COMMIT;
