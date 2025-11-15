-- Phase 2 GDELT performance indexing (adapted to existing column names)
-- Safe, idempotent: uses IF NOT EXISTS where supported.

-- Add missing columns for future enrichment/state tracking
ALTER TABLE gdelt_events ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE gdelt_events ADD COLUMN IF NOT EXISTS processed BOOLEAN DEFAULT false;

-- Core query indexes
CREATE INDEX IF NOT EXISTS idx_gdelt_sql_date ON gdelt_events (sql_date DESC);
CREATE INDEX IF NOT EXISTS idx_gdelt_action_country ON gdelt_events (action_country);
CREATE INDEX IF NOT EXISTS idx_gdelt_goldstein ON gdelt_events (goldstein) WHERE goldstein < -5;
CREATE INDEX IF NOT EXISTS idx_gdelt_quad_class ON gdelt_events (quad_class) WHERE quad_class IN (3,4);

-- Geospatial proximity (lat/long) – note: not a true GiST/earthdistance index; upgrade later
CREATE INDEX IF NOT EXISTS idx_gdelt_coordinates ON gdelt_events (action_lat, action_long) WHERE action_lat IS NOT NULL;

-- Source URL lookup (using btree; hash optional but btree better for flexibility)
CREATE INDEX IF NOT EXISTS idx_gdelt_source_url ON gdelt_events USING btree (source_url);

-- Composite threat query accelerator
CREATE INDEX IF NOT EXISTS idx_gdelt_threat_query ON gdelt_events (sql_date DESC, action_country, goldstein)
  WHERE quad_class IN (3,4) AND goldstein < -5;

-- Unprocessed workflow items
CREATE INDEX IF NOT EXISTS idx_gdelt_processed ON gdelt_events (processed) WHERE processed = false;

-- Future: consider GiST/ SP-GiST on (point(action_lat, action_long)) for geometric queries