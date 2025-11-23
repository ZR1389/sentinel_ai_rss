-- 005_geofenced_alerts.sql
-- Adds basic alert tracking fields to travel_itineraries for geofenced alerts feature.

ALTER TABLE travel_itineraries
    ADD COLUMN IF NOT EXISTS last_alert_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS alerts_sent_count INTEGER DEFAULT 0;

-- Future enhancements (not applied now):
-- ALTER TABLE travel_itineraries ADD COLUMN IF NOT EXISTS alerts_last_hash TEXT;
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_itineraries_alerts_count ON travel_itineraries(alerts_sent_count);
