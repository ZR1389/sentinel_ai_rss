-- OpenCage Geocoding Migration
-- Adds PostGIS spatial support and geocoding tables to existing Sentinel AI database
-- Note: This extends your existing schema - does NOT create new database

-- ============================================================
-- 1. Enable PostGIS Extension (if not already enabled)
-- ============================================================
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- 2. Create geocoded_locations table (persistent cache)
-- ============================================================
-- This replaces the simple geocode_cache with a richer PostGIS-enabled version
CREATE TABLE IF NOT EXISTS geocoded_locations (
    id SERIAL PRIMARY KEY,
    location_text TEXT UNIQUE NOT NULL,     -- Original text: "Paris, France"
    normalized_text TEXT,                   -- Cleaned version
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    geom GEOGRAPHY(POINT, 4326),           -- PostGIS geography for distance queries
    country_code VARCHAR(5),
    admin_level_1 TEXT,                    -- State/province
    admin_level_2 TEXT,                    -- City/county
    confidence INTEGER,                    -- OpenCage confidence (1-10)
    source VARCHAR(50) DEFAULT 'opencage',
    created_at TIMESTAMPTZ DEFAULT now(),
    last_used_at TIMESTAMPTZ DEFAULT now(),
    use_count INTEGER DEFAULT 0            -- Track cache hits
);

-- Spatial index for fast proximity queries
CREATE INDEX IF NOT EXISTS idx_geocoded_geom ON geocoded_locations USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_geocoded_lookup ON geocoded_locations(location_text);
CREATE INDEX IF NOT EXISTS idx_geocoded_country ON geocoded_locations(country_code);
CREATE INDEX IF NOT EXISTS idx_geocoded_last_used ON geocoded_locations(last_used_at);

-- ============================================================
-- 3. Add geom columns to existing tables (NO DATA LOSS)
-- ============================================================
-- Keep existing lat/lon for backwards compatibility
-- Add geom alongside for spatial queries

-- alerts table
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS geom GEOGRAPHY(POINT, 4326);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS geocoded_location_id INTEGER REFERENCES geocoded_locations(id);
CREATE INDEX IF NOT EXISTS idx_alerts_geom ON alerts USING GIST(geom);

-- raw_alerts table
ALTER TABLE raw_alerts ADD COLUMN IF NOT EXISTS geom GEOGRAPHY(POINT, 4326);
ALTER TABLE raw_alerts ADD COLUMN IF NOT EXISTS geocoded_location_id INTEGER REFERENCES geocoded_locations(id);
CREATE INDEX IF NOT EXISTS idx_raw_alerts_geom ON raw_alerts USING GIST(geom);

-- Backfill geom from existing lat/lon (run after migration)
-- UPDATE alerts SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
-- WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND geom IS NULL;

-- UPDATE raw_alerts SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
-- WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND geom IS NULL;

-- ============================================================
-- 4. Traveler profiles (for proximity alerts)
-- ============================================================
CREATE TABLE IF NOT EXISTS traveler_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,                       -- Link to your users table
    email TEXT,
    current_location TEXT,
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    geom GEOGRAPHY(POINT, 4326),
    alert_radius_km INTEGER DEFAULT 50,
    active BOOLEAN DEFAULT true,
    last_alert_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_traveler_geom ON traveler_profiles USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_traveler_active ON traveler_profiles(active) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_traveler_user_id ON traveler_profiles(user_id);

-- ============================================================
-- 5. Proximity alert history (prevent spam)
-- ============================================================
CREATE TABLE IF NOT EXISTS proximity_alerts (
    id SERIAL PRIMARY KEY,
    traveler_id INTEGER REFERENCES traveler_profiles(id) ON DELETE CASCADE,
    threat_id INTEGER,                     -- References alerts.id
    threat_source VARCHAR(50),             -- 'rss', 'gdelt', 'acled', 'apify'
    distance_km DECIMAL(6, 2),
    severity_score DECIMAL(4, 2),
    sent_at TIMESTAMPTZ DEFAULT now(),
    alert_method VARCHAR(20),              -- 'email', 'sms', 'push'
    alert_payload JSONB                    -- Store full alert context
);

CREATE INDEX IF NOT EXISTS idx_proximity_traveler ON proximity_alerts(traveler_id);
CREATE INDEX IF NOT EXISTS idx_proximity_threat ON proximity_alerts(threat_id);
CREATE INDEX IF NOT EXISTS idx_proximity_sent_at ON proximity_alerts(sent_at);

-- ============================================================
-- 6. OpenCage quota tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS geocoding_quota_log (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    request_count INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    api_calls INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(date)
);

CREATE INDEX IF NOT EXISTS idx_quota_date ON geocoding_quota_log(date DESC);

-- ============================================================
-- 7. Helper functions for spatial queries
-- ============================================================

-- Function: Find threats within radius of a location
CREATE OR REPLACE FUNCTION find_threats_near_location(
    target_lat DECIMAL,
    target_lon DECIMAL,
    radius_km INTEGER DEFAULT 50,
    days_back INTEGER DEFAULT 7
)
RETURNS TABLE (
    threat_id INTEGER,
    title TEXT,
    distance_km DECIMAL,
    severity_score DECIMAL,
    published TIMESTAMPTZ,
    threat_type TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.id,
        a.title,
        ROUND(ST_Distance(
            a.geom::geography,
            ST_SetSRID(ST_MakePoint(target_lon, target_lat), 4326)::geography
        ) / 1000, 2) AS distance_km,
        COALESCE(a.score::DECIMAL, 0) AS severity_score,
        a.published,
        a.threat_type
    FROM alerts a
    WHERE a.geom IS NOT NULL
      AND a.published >= now() - (days_back || ' days')::interval
      AND ST_DWithin(
          a.geom::geography,
          ST_SetSRID(ST_MakePoint(target_lon, target_lat), 4326)::geography,
          radius_km * 1000  -- Convert km to meters
      )
    ORDER BY distance_km ASC;
END;
$$ LANGUAGE plpgsql;

-- Function: Update quota log (upsert)
CREATE OR REPLACE FUNCTION log_geocoding_request(
    is_cache_hit BOOLEAN,
    is_error BOOLEAN DEFAULT false
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO geocoding_quota_log (date, request_count, cache_hits, api_calls, errors)
    VALUES (
        CURRENT_DATE,
        1,
        CASE WHEN is_cache_hit THEN 1 ELSE 0 END,
        CASE WHEN NOT is_cache_hit AND NOT is_error THEN 1 ELSE 0 END,
        CASE WHEN is_error THEN 1 ELSE 0 END
    )
    ON CONFLICT (date) DO UPDATE SET
        request_count = geocoding_quota_log.request_count + 1,
        cache_hits = geocoding_quota_log.cache_hits + CASE WHEN is_cache_hit THEN 1 ELSE 0 END,
        api_calls = geocoding_quota_log.api_calls + CASE WHEN NOT is_cache_hit AND NOT is_error THEN 1 ELSE 0 END,
        errors = geocoding_quota_log.errors + CASE WHEN is_error THEN 1 ELSE 0 END;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 8. Verification queries (run after migration)
-- ============================================================

-- Check PostGIS version
-- SELECT PostGIS_Version();

-- Check spatial columns added
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name IN ('alerts', 'raw_alerts', 'traveler_profiles') 
-- AND column_name = 'geom';

-- Check geocoded_locations table
-- SELECT COUNT(*) FROM geocoded_locations;

-- Test spatial function
-- SELECT * FROM find_threats_near_location(6.5244, 3.3792, 50, 7);  -- Lagos, Nigeria

COMMENT ON TABLE geocoded_locations IS 'Persistent geocoding cache with PostGIS support';
COMMENT ON TABLE traveler_profiles IS 'User location profiles for proximity alerting';
COMMENT ON TABLE proximity_alerts IS 'History of sent proximity alerts to prevent spam';
COMMENT ON TABLE geocoding_quota_log IS 'Daily OpenCage API quota tracking';
