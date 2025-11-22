-- ============================================
-- Plan System Update Migration (002)
-- ============================================

-- Add lifetime counters for free users
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS lifetime_chat_messages INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS lifetime_travel_assessments INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS lifetime_map_views INTEGER DEFAULT 0;

-- Add trial management
ALTER TABLE users
ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS is_trial BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255);

-- Feature usage tracking table
CREATE TABLE IF NOT EXISTS feature_usage (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    feature VARCHAR(50) NOT NULL,
    usage_count INTEGER DEFAULT 1,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, feature, period_start)
);

CREATE INDEX IF NOT EXISTS idx_feature_usage_user ON feature_usage(user_id, period_start);
CREATE INDEX IF NOT EXISTS idx_feature_usage_feature ON feature_usage(feature);

-- Saved searches / monitors
CREATE TABLE IF NOT EXISTS saved_searches (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    query JSONB NOT NULL,
    alert_enabled BOOLEAN DEFAULT TRUE,
    alert_frequency VARCHAR(20) DEFAULT 'daily', -- 'realtime', 'hourly', 'daily', 'weekly'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_searches_user ON saved_searches(user_id);

-- Trip plans
CREATE TABLE IF NOT EXISTS trip_plans (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    destinations JSONB NOT NULL, -- [{name, lat, lon, start_date, end_date}]
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trip_plans_user ON trip_plans(user_id);

-- Initialize lifetime counters if NULL
UPDATE users SET 
    lifetime_chat_messages = COALESCE(lifetime_chat_messages, 0),
    lifetime_travel_assessments = COALESCE(lifetime_travel_assessments, 0),
    lifetime_map_views = COALESCE(lifetime_map_views, 0)
WHERE lifetime_chat_messages IS NULL OR lifetime_travel_assessments IS NULL OR lifetime_map_views IS NULL;

-- Plan change history
CREATE TABLE IF NOT EXISTS plan_changes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    from_plan VARCHAR(20),
    to_plan VARCHAR(20) NOT NULL,
    changed_at TIMESTAMP DEFAULT NOW(),
    reason VARCHAR(255), -- 'upgrade', 'downgrade', 'trial_start', 'trial_end', 'payment_failed'
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_plan_changes_user ON plan_changes(user_id);
CREATE INDEX IF NOT EXISTS idx_plan_changes_date ON plan_changes(changed_at);

-- Documentation comments
COMMENT ON COLUMN users.lifetime_chat_messages IS 'Total chat messages used across all time (for free tier limit tracking)';
COMMENT ON COLUMN users.lifetime_travel_assessments IS 'Total travel risk assessments performed (for free tier limit tracking)';
COMMENT ON COLUMN users.trial_started_at IS 'When user started their trial (NULL if never trialed)';
COMMENT ON COLUMN users.trial_ends_at IS 'When trial expires (used to auto-downgrade)';
COMMENT ON COLUMN users.is_trial IS 'Whether user is currently on a trial';

-- Increment feature usage function
CREATE OR REPLACE FUNCTION increment_feature_usage(
    p_user_id INTEGER,
    p_feature VARCHAR(50)
) RETURNS void AS $$
DECLARE
    v_period_start DATE;
    v_period_end DATE;
BEGIN
    v_period_start := DATE_TRUNC('month', CURRENT_DATE);
    v_period_end := (DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month' - INTERVAL '1 day')::DATE;
    INSERT INTO feature_usage (user_id, feature, usage_count, period_start, period_end)
    VALUES (p_user_id, p_feature, 1, v_period_start, v_period_end)
    ON CONFLICT (user_id, feature, period_start)
    DO UPDATE SET usage_count = feature_usage.usage_count + 1;
END;
$$ LANGUAGE plpgsql;

-- Check feature limit function
CREATE OR REPLACE FUNCTION check_feature_limit(
    p_user_id INTEGER,
    p_feature VARCHAR(50),
    p_limit INTEGER
) RETURNS BOOLEAN AS $$
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
    RETURN v_usage < p_limit;
END;
$$ LANGUAGE plpgsql;
