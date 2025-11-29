-- Migration: Create location_validations table for OpenCage quality checks
-- Purpose: Track 1% sample validations and anomaly investigations

CREATE TABLE IF NOT EXISTS location_validations (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
    validated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- OpenCage results
    opencage_lat DOUBLE PRECISION,
    opencage_lon DOUBLE PRECISION,
    opencage_country VARCHAR(10),
    opencage_confidence INTEGER,
    opencage_source VARCHAR(50),
    
    -- Comparison metrics
    distance_km DOUBLE PRECISION,
    needs_correction BOOLEAN DEFAULT FALSE,
    validation_query TEXT,
    
    -- Tracking
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(alert_id)
);

-- Index for querying recent validations
CREATE INDEX IF NOT EXISTS idx_location_validations_validated_at 
    ON location_validations(validated_at DESC);

-- Index for finding corrections needed
CREATE INDEX IF NOT EXISTS idx_location_validations_needs_correction 
    ON location_validations(needs_correction) 
    WHERE needs_correction = TRUE;

-- Index for distance analysis
CREATE INDEX IF NOT EXISTS idx_location_validations_distance 
    ON location_validations(distance_km) 
    WHERE distance_km IS NOT NULL;

COMMENT ON TABLE location_validations IS 'Tracks OpenCage API validations for location quality assurance (1% sampling + anomalies)';
COMMENT ON COLUMN location_validations.distance_km IS 'Distance between original coordinates and OpenCage result (km)';
COMMENT ON COLUMN location_validations.needs_correction IS 'TRUE if distance > 100km (likely incorrect location)';
