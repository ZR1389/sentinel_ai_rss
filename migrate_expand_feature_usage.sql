-- Expand feature_usage tracking system beyond chat
-- This migration adds comprehensive feature usage tracking for all metered features

-- Add indices for efficient feature usage queries
CREATE INDEX IF NOT EXISTS idx_feature_usage_user_feature_period 
ON feature_usage(user_id, feature, period_start DESC);

CREATE INDEX IF NOT EXISTS idx_feature_usage_period_start 
ON feature_usage(period_start) 
WHERE period_start >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '3 months');

COMMENT ON INDEX idx_feature_usage_user_feature_period IS 
'Composite index for fast user+feature lookups with recent periods first';

-- Create function to safely increment feature usage with logging
CREATE OR REPLACE FUNCTION increment_feature_usage_safe(
    p_user_id INTEGER,
    p_feature VARCHAR(50),
    p_increment INTEGER DEFAULT 1
) RETURNS INTEGER AS $$
DECLARE
    v_period_start DATE;
    v_period_end DATE;
    v_new_count INTEGER;
BEGIN
    v_period_start := DATE_TRUNC('month', CURRENT_DATE);
    v_period_end := (DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month' - INTERVAL '1 day')::DATE;
    
    INSERT INTO feature_usage (user_id, feature, usage_count, period_start, period_end)
    VALUES (p_user_id, p_feature, p_increment, v_period_start, v_period_end)
    ON CONFLICT (user_id, feature, period_start)
    DO UPDATE SET 
        usage_count = feature_usage.usage_count + p_increment,
        updated_at = NOW()
    RETURNING usage_count INTO v_new_count;
    
    RETURN v_new_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION increment_feature_usage_safe IS 
'Safely increment feature usage counter. Returns new count. Supports bulk increments.';

-- Create function to get current monthly usage
CREATE OR REPLACE FUNCTION get_feature_usage(
    p_user_id INTEGER,
    p_feature VARCHAR(50)
) RETURNS INTEGER AS $$
DECLARE
    v_usage INTEGER;
    v_period_start DATE;
BEGIN
    v_period_start := DATE_TRUNC('month', CURRENT_DATE);
    
    SELECT COALESCE(usage_count, 0) INTO v_usage
    FROM feature_usage
    WHERE user_id = p_user_id 
      AND feature = p_feature
      AND period_start = v_period_start;
    
    RETURN COALESCE(v_usage, 0);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_feature_usage IS 
'Get current monthly usage count for a specific feature and user';

-- Create function to get all user feature usage for current month
CREATE OR REPLACE FUNCTION get_user_feature_usage(
    p_user_id INTEGER
) RETURNS TABLE (
    feature VARCHAR(50),
    usage_count INTEGER,
    period_start DATE,
    period_end DATE,
    last_used TIMESTAMPTZ
) AS $$
DECLARE
    v_period_start DATE;
BEGIN
    v_period_start := DATE_TRUNC('month', CURRENT_DATE);
    
    RETURN QUERY
    SELECT 
        fu.feature,
        fu.usage_count,
        fu.period_start,
        fu.period_end,
        fu.updated_at as last_used
    FROM feature_usage fu
    WHERE fu.user_id = p_user_id 
      AND fu.period_start = v_period_start
    ORDER BY fu.feature;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_user_feature_usage IS 
'Get all feature usage stats for a user in current month';

-- Create function to reset usage for new billing period (called by cron)
CREATE OR REPLACE FUNCTION archive_old_feature_usage() RETURNS INTEGER AS $$
DECLARE
    v_archived_count INTEGER;
BEGIN
    -- Archive feature_usage records older than 6 months for audit trail
    -- This keeps the table size manageable while preserving historical data
    WITH archived AS (
        DELETE FROM feature_usage
        WHERE period_start < DATE_TRUNC('month', CURRENT_DATE - INTERVAL '6 months')
        RETURNING *
    )
    SELECT COUNT(*) INTO v_archived_count FROM archived;
    
    RETURN v_archived_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION archive_old_feature_usage IS 
'Archive feature_usage records older than 6 months. Run monthly via cron.';

-- Create materialized view for feature usage analytics (optional)
CREATE MATERIALIZED VIEW IF NOT EXISTS feature_usage_summary AS
SELECT 
    feature,
    period_start,
    COUNT(DISTINCT user_id) as unique_users,
    SUM(usage_count) as total_usage,
    AVG(usage_count) as avg_usage_per_user,
    MAX(usage_count) as max_usage,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY usage_count) as median_usage
FROM feature_usage
WHERE period_start >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '3 months')
GROUP BY feature, period_start
ORDER BY period_start DESC, feature;

CREATE UNIQUE INDEX IF NOT EXISTS idx_feature_usage_summary_unique 
ON feature_usage_summary(feature, period_start);

COMMENT ON MATERIALIZED VIEW feature_usage_summary IS 
'Aggregated feature usage statistics for analytics dashboard. Refresh monthly.';

-- Verify existing feature_usage records
DO $$
DECLARE
    total_records INTEGER;
    unique_features INTEGER;
    current_month_records INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_records FROM feature_usage;
    SELECT COUNT(DISTINCT feature) INTO unique_features FROM feature_usage;
    SELECT COUNT(*) INTO current_month_records 
    FROM feature_usage 
    WHERE period_start = DATE_TRUNC('month', CURRENT_DATE);
    
    RAISE NOTICE 'Feature usage tracking status:';
    RAISE NOTICE '  Total records: %', total_records;
    RAISE NOTICE '  Unique features tracked: %', unique_features;
    RAISE NOTICE '  Current month records: %', current_month_records;
END $$;

-- List of features to track (for reference and validation)
-- This is documentation; actual tracking happens in application code via decorators
/*
FEATURES TO TRACK:
- chat_messages_monthly: Chat message usage (already tracked)
- saved_searches_created: Number of saved searches created
- itinerary_destinations_added: Total destinations across all itineraries
- itinerary_route_analyses: Route analysis requests
- briefing_packages_generated: Briefing package exports
- monthly_briefings_generated: Monthly briefing generations
- pdf_exports: PDF export operations
- api_token_usage: API token requests (if applicable)
- team_invites_sent: Team member invitations
- custom_reports_generated: Custom report generations
- analyst_intelligence_queries: Analyst intelligence requests
- safe_zone_queries: Safe zone overlay requests
- alert_exports: Alert export operations
*/

-- Ensure updated_at column exists on feature_usage
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'feature_usage' 
        AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE feature_usage 
        ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
        
        CREATE INDEX idx_feature_usage_updated_at 
        ON feature_usage(updated_at DESC);
        
        RAISE NOTICE 'Added updated_at column to feature_usage table';
    END IF;
END $$;
