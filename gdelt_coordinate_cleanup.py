"""gdelt_coordinate_cleanup.py

One-off maintenance script to sanitize existing GDELT-derived raw_alerts with invalid
coordinates that block Threat Engine validation.

Actions:
  - Set latitude/longitude to NULL where out of valid range or longitude = 0 (unknown)
  - Append a geo_correction tag noting the cleanup
  - Report counts of affected rows before and after

Usage:
  python gdelt_coordinate_cleanup.py            # perform cleanup
  python gdelt_coordinate_cleanup.py --dry-run  # show counts only, no modification

Environment:
  Uses standard db_utils._get_db_connection resolution (DATABASE_URL / bootstrap overrides)

After running, re-run threat_engine to allow previously invalid alerts to proceed.
"""
from __future__ import annotations
import argparse
from logging_config import get_logger

logger = get_logger("gdelt_cleanup")

def get_conn_cm():
    try:
        from db_utils import _get_db_connection
        return _get_db_connection
    except Exception as e:
        logger.error("DB connection helper unavailable: %s", e)
        return None

def count_invalid(cur):
    cur.execute("""
        SELECT COUNT(*) FROM raw_alerts
        WHERE source='gdelt' AND (
            longitude=0 OR longitude < -180 OR longitude > 180 OR
            latitude < -90 OR latitude > 90
        )
    """)
    return cur.fetchone()[0]

def perform_cleanup(dry_run: bool=False):
    get_conn = get_conn_cm()
    if not get_conn:
        return {"error": "db unavailable"}
    with get_conn() as conn:
        cur = conn.cursor()
        before = count_invalid(cur)
        if dry_run:
            logger.info("Dry run: %d invalid coordinate raw_alert rows detected", before)
            return {"invalid_rows": before, "dry_run": True}

        if before == 0:
            logger.info("No invalid coordinate rows found; nothing to do")
            return {"invalid_rows": 0, "updated": 0}

        logger.info("Cleaning %d raw_alerts with invalid coordinates...", before)
        cur.execute("""
            UPDATE raw_alerts
            SET latitude = NULL,
                longitude = NULL,
                tags = CASE 
                    WHEN jsonb_typeof(tags)='array' THEN tags || '[{"geo_correction":"invalid_coords_nullified"}]'::jsonb
                    ELSE tags
                END
            WHERE source='gdelt' AND (
                longitude=0 OR longitude < -180 OR longitude > 180 OR
                latitude < -90 OR latitude > 90
            )
        """)
        updated = cur.rowcount
        conn.commit()
        after = count_invalid(cur)
        logger.info("✓ Cleanup complete: %d rows updated; remaining invalid: %d", updated, after)
        return {"invalid_before": before, "updated": updated, "invalid_after": after}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sanitize invalid GDELT raw_alert coordinates")
    parser.add_argument("--dry-run", action="store_true", help="Report counts only; no changes")
    args = parser.parse_args()
    result = perform_cleanup(dry_run=args.dry_run)
    print(result)
