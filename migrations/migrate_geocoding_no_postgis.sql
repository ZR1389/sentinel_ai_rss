-- ============================================================================
-- GEOCODING TABLES (No PostGIS - Railway PostgreSQL)
-- ============================================================================

-- Geocoded locations cache (persistent)
CREATE TABLE IF NOT EXISTS geocoded_locations (
    id SERIAL PRIMARY KEY,
    location_text TEXT UNIQUE NOT NULL,
    normalized_text TEXT,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    country_code VARCHAR(5),
    admin_level_1 TEXT,
    admin_level_2 TEXT,
    confidence INTEGER,
    source VARCHAR(50) DEFAULT 'opencage',
    created_at TIMESTAMPTZ DEFAULT now(),
    last_used_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_geocoded_lookup ON geocoded_locations(location_text);
CREATE INDEX IF NOT EXISTS idx_geocoded_normalized ON geocoded_locations(normalized_text);
CREATE INDEX IF NOT EXISTS idx_geocoded_latlon ON geocoded_locations(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_geocoded_country ON geocoded_locations(country_code);

-- ============================================================================
-- TRAVELER PROFILES
-- ============================================================================

CREATE TABLE IF NOT EXISTS traveler_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    email TEXT NOT NULL,
    name TEXT,
    current_location TEXT,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    country_code VARCHAR(5),
    alert_radius_km INTEGER DEFAULT 50,
    active BOOLEAN DEFAULT true,
    last_alert_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_traveler_latlon ON traveler_profiles(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_traveler_active ON traveler_profiles(active) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_traveler_email ON traveler_profiles(email);

-- ============================================================================
-- PROXIMITY ALERTS LOG
-- ============================================================================

CREATE TABLE IF NOT EXISTS proximity_alerts (
    id SERIAL PRIMARY KEY,
    traveler_id INTEGER REFERENCES traveler_profiles(id) ON DELETE CASCADE,
    threat_id BIGINT,
    threat_source VARCHAR(50),  -- 'gdelt', 'rss', 'acled', 'apify'
    threat_date DATE,
    distance_km NUMERIC(6, 2),
    severity_score NUMERIC(4, 2),
    alert_method VARCHAR(20),  -- 'email', 'sms', 'push'
    sent_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_proximity_traveler ON proximity_alerts(traveler_id);
CREATE INDEX IF NOT EXISTS idx_proximity_sent_at ON proximity_alerts(sent_at);

-- ============================================================================
-- UPDATE EXISTING TABLES (Add lat/lon if missing)
-- ============================================================================

-- GDELT events (already has action_lat/action_long)
ALTER TABLE gdelt_events 
ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 7),
ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 7);

-- Populate from existing columns
UPDATE gdelt_events 
SET latitude = action_lat, longitude = action_long
WHERE latitude IS NULL AND action_lat IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_gdelt_latlon ON gdelt_events(latitude, longitude);

-- Alerts table (main enriched alerts)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alerts') THEN
        ALTER TABLE alerts ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 7);
        ALTER TABLE alerts ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 7);
        ALTER TABLE alerts ADD COLUMN IF NOT EXISTS geocoded_location_id INTEGER REFERENCES geocoded_locations(id);
        
        CREATE INDEX IF NOT EXISTS idx_alerts_latlon ON alerts(latitude, longitude);
    END IF;
END $$;

-- Raw alerts table
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'raw_alerts') THEN
        ALTER TABLE raw_alerts ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 7);
        ALTER TABLE raw_alerts ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 7);
        ALTER TABLE raw_alerts ADD COLUMN IF NOT EXISTS geocoded_location_id INTEGER REFERENCES geocoded_locations(id);
        
        CREATE INDEX IF NOT EXISTS idx_raw_alerts_latlon ON raw_alerts(latitude, longitude);
    END IF;
END $$;
