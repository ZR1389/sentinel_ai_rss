-- Add location intelligence fields to alerts table
ALTER TABLE alerts 
ADD COLUMN IF NOT EXISTS location_method text,
ADD COLUMN IF NOT EXISTS location_confidence text,
ADD COLUMN IF NOT EXISTS location_sharing boolean DEFAULT true;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_alerts_location_confidence ON alerts(location_confidence);
CREATE INDEX IF NOT EXISTS idx_alerts_location_method ON alerts(location_method);

-- Update existing records with reasonable defaults
UPDATE alerts 
SET 
    location_method = CASE 
        WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 'coordinates'
        WHEN country IS NOT NULL AND city IS NOT NULL THEN 'moderate'
        WHEN country IS NOT NULL THEN 'low'
        ELSE 'unknown'
    END,
    location_confidence = CASE 
        WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 'high'
        WHEN country IS NOT NULL AND city IS NOT NULL THEN 'medium'
        WHEN country IS NOT NULL THEN 'low'
        ELSE 'none'
    END,
    location_sharing = true
WHERE location_method IS NULL;
