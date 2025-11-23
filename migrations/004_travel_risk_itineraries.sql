-- Migration 004: Travel Risk Itineraries
-- Creates table for storing user travel itineraries with route analysis

-- Create travel_itineraries table
CREATE TABLE IF NOT EXISTS travel_itineraries (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    itinerary_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
    
    -- Metadata
    title VARCHAR(255),
    description TEXT,
    
    -- Itinerary data (JSONB for flexibility)
    -- Expected structure: {waypoints: [...], routes: [...], risk_analysis: {...}, metadata: {...}}
    data JSONB NOT NULL,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Soft delete
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    
    -- Version tracking (for future edit support)
    version INTEGER NOT NULL DEFAULT 1,
    
    -- Constraints
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT unique_itinerary_uuid UNIQUE (itinerary_uuid)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_itineraries_user_created 
    ON travel_itineraries(user_id, created_at DESC) 
    WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_itineraries_uuid 
    ON travel_itineraries(itinerary_uuid) 
    WHERE is_deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_itineraries_user_active 
    ON travel_itineraries(user_id) 
    WHERE is_deleted = FALSE;

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_itinerary_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at
CREATE TRIGGER trigger_itinerary_updated_at
    BEFORE UPDATE ON travel_itineraries
    FOR EACH ROW
    EXECUTE FUNCTION update_itinerary_updated_at();

-- View for active itineraries with user info
CREATE OR REPLACE VIEW active_itineraries AS
SELECT 
    ti.id,
    ti.itinerary_uuid,
    ti.user_id,
    u.email as user_email,
    ti.title,
    ti.description,
    ti.data,
    ti.created_at,
    ti.updated_at,
    ti.version
FROM travel_itineraries ti
JOIN users u ON ti.user_id = u.id
WHERE ti.is_deleted = FALSE;

-- Comments for documentation
COMMENT ON TABLE travel_itineraries IS 'Stores user travel itineraries with route risk analysis';
COMMENT ON COLUMN travel_itineraries.data IS 'JSONB containing waypoints, routes, risk_analysis, and metadata';
COMMENT ON COLUMN travel_itineraries.version IS 'Version number for tracking edits (future feature)';
COMMENT ON INDEX idx_itineraries_user_created IS 'Fast lookup for user dashboard listing ordered by creation date';
