-- GDELT metrics tracking table for monitoring ingestion performance

CREATE TABLE IF NOT EXISTS gdelt_metrics (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT now(),
    ingestion_duration_sec DECIMAL(10, 3),
    events_downloaded INTEGER DEFAULT 0,
    events_inserted INTEGER DEFAULT 0,
    events_skipped INTEGER DEFAULT 0,
    retries_performed INTEGER DEFAULT 0,
    filename TEXT,
    last_error TEXT
);

-- Index for time-series queries
CREATE INDEX IF NOT EXISTS idx_gdelt_metrics_timestamp ON gdelt_metrics(timestamp DESC);
