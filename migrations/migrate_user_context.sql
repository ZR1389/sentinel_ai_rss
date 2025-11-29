-- Phase 1: User Context Table for Sentinel AI Products
-- This table stores user context across Chat, Threat Map, and Travel Risk Map

CREATE TABLE IF NOT EXISTS user_context (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    active_investigation JSONB,
    recent_queries JSONB DEFAULT '[]'::jsonb,
    saved_locations JSONB DEFAULT '[]'::jsonb,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_context_user_id ON user_context(user_id);

-- Add trigger to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_user_context_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_user_context_timestamp
    BEFORE UPDATE ON user_context
    FOR EACH ROW
    EXECUTE FUNCTION update_user_context_timestamp();

-- Comments for documentation
COMMENT ON TABLE user_context IS 'Stores user context and state across Sentinel AI Chat, Threat Map, and Travel Risk Map';
COMMENT ON COLUMN user_context.user_id IS 'Foreign key to users table';
COMMENT ON COLUMN user_context.active_investigation IS 'Current investigation context for Sentinel AI Chat';
COMMENT ON COLUMN user_context.recent_queries IS 'Array of recent search queries across all products';
COMMENT ON COLUMN user_context.saved_locations IS 'Array of saved locations for Threat Map and Travel Risk Map';
COMMENT ON COLUMN user_context.updated_at IS 'Last update timestamp, automatically managed by trigger';
