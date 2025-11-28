-- Remove ACLED and GDELT map aggregates to avoid frontend/backend issues with poor data quality
-- These sources are disabled/removed from ingestion anyway

BEGIN;

DO $$
DECLARE 
    acled_count int;
    gdelt_count int;
BEGIN
    SELECT COUNT(*) INTO acled_count FROM map_aggregates WHERE source='acled';
    SELECT COUNT(*) INTO gdelt_count FROM map_aggregates WHERE source='gdelt';
    
    RAISE NOTICE 'Pre-delete: acled=% gdelt=%', acled_count, gdelt_count;
    
    DELETE FROM map_aggregates WHERE source IN ('acled', 'gdelt');
    
    SELECT COUNT(*) INTO acled_count FROM map_aggregates WHERE source='acled';
    SELECT COUNT(*) INTO gdelt_count FROM map_aggregates WHERE source='gdelt';
    
    RAISE NOTICE 'Post-delete: acled=% gdelt=%', acled_count, gdelt_count;
END $$;

COMMIT;
