-- Add threat_score_components column to alerts table
-- This stores the breakdown of how the threat score was calculated

ALTER TABLE alerts 
ADD COLUMN IF NOT EXISTS threat_score_components JSONB;

-- Create index for faster queries on alerts with SOCMINT data
CREATE INDEX IF NOT EXISTS idx_alerts_threat_components 
ON alerts USING gin (threat_score_components);

-- Example threat_score_components structure:
-- {
--   "socmint_raw": 15.0,
--   "socmint_weighted": 4.5,
--   "socmint_weight": 0.3,
--   "base_score": 60.0,
--   "final_score": 64.5
-- }

COMMENT ON COLUMN alerts.threat_score_components IS 
'JSONB breakdown of threat scoring factors including SOCMINT contribution';
