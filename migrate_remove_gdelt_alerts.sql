-- Remove all GDELT-sourced alerts (one-time cleanup)
-- Provides before/after counts for auditability

BEGIN;

DO $$
DECLARE pre_raw int; pre_alerts int; post_raw int; post_alerts int; 
BEGIN
    SELECT COUNT(*) INTO pre_raw FROM raw_alerts WHERE source='gdelt';
    SELECT COUNT(*) INTO pre_alerts FROM alerts WHERE source='gdelt';
    RAISE NOTICE 'Pre-delete counts: raw_alerts=% alerts=%', pre_raw, pre_alerts;

    -- Delete child table first if any dependencies (alerts may reference raw_alerts uuid historically)
    DELETE FROM alerts WHERE source='gdelt';
    DELETE FROM raw_alerts WHERE source='gdelt';

    SELECT COUNT(*) INTO post_raw FROM raw_alerts WHERE source='gdelt';
    SELECT COUNT(*) INTO post_alerts FROM alerts WHERE source='gdelt';
    RAISE NOTICE 'Post-delete counts: raw_alerts=% alerts=%', post_raw, post_alerts;
END $$;

COMMIT;
