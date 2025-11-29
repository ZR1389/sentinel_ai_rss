-- Migration script: migrate_score_type.sql
BEGIN;

-- Check current types first
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'alerts' 
  AND column_name IN ('score', 'confidence');

-- If they are 'text' or 'character varying', run:
ALTER TABLE alerts 
ALTER COLUMN score TYPE numeric USING score::numeric,
ALTER COLUMN confidence TYPE numeric USING confidence::numeric;

-- Add constraints to prevent invalid data
ALTER TABLE alerts 
ADD CONSTRAINT score_range CHECK (score >= 0 AND score <= 100),
ADD CONSTRAINT confidence_range CHECK (confidence >= 0 AND confidence <= 1);

-- Update existing rows with NULL values to safe defaults
UPDATE alerts SET score = 0 WHERE score IS NULL;
UPDATE alerts SET confidence = 0.5 WHERE confidence IS NULL;

-- Create indexes for numeric queries
CREATE INDEX idx_alerts_score_numeric ON alerts (score) WHERE score > 50;
CREATE INDEX idx_alerts_confidence_numeric ON alerts (confidence) WHERE confidence > 0.7;

COMMIT;
