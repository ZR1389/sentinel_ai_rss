-- Migration: add persistent over-limit flag to saved_searches
-- Date: 2025-11-23
-- Purpose: Track saved searches exceeding a user's current plan limit so UI can
--          soft-disable alerts and highlight upgrade suggestions without recomputing each time.
-- Safety: Uses IF NOT EXISTS to avoid errors on re-run.

ALTER TABLE saved_searches
    ADD COLUMN IF NOT EXISTS is_over_limit BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN saved_searches.is_over_limit IS 'True when entry exceeds current plan limit; alerts should be disabled';

-- Optional future index if query volume requires (commented out):
-- CREATE INDEX IF NOT EXISTS idx_saved_searches_over_limit ON saved_searches (user_id, is_over_limit);
