#!/usr/bin/env python3
"""Apply user_context migration to Railway database."""

import os
import psycopg2

def apply_migration():
    db_url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_PUBLIC_URL or DATABASE_URL not set")
        return False
    
    migration_sql = """
-- Phase 1: User Context Table for Sentinel AI Products
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

DROP TRIGGER IF EXISTS trigger_update_user_context_timestamp ON user_context;
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
"""
    
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        print("Applying user_context migration...")
        cur.execute(migration_sql)
        conn.commit()
        
        print("✓ Migration applied successfully")
        
        # Verify table exists
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'user_context'")
        count = cur.fetchone()[0]
        if count == 1:
            print("✓ user_context table verified")
        else:
            print("✗ Table verification failed")
            return False
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    success = apply_migration()
    exit(0 if success else 1)
