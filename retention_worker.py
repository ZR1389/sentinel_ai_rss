# retention_worker.py - Run as Railway background worker
import os
import logging
from datetime import datetime, timedelta, timezone
from db_utils import execute

logger = logging.getLogger("retention_worker")

def cleanup_old_alerts():
    """Delete alerts older than retention period"""
    retention_days = int(os.getenv("ALERT_RETENTION_DAYS", "90"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    
    logger.info(f"Starting cleanup: removing alerts older than {retention_days} days (before {cutoff})")
    
    try:
        # Delete raw alerts first (older than enriched)
        raw_result = execute(
            "DELETE FROM raw_alerts WHERE published < %s",
            (cutoff,),
            fetch=False
        )
        logger.info(f"Deleted raw alerts: {raw_result if raw_result else 'completed'}")
        
        # Then delete enriched alerts
        alerts_result = execute(
            "DELETE FROM alerts WHERE published < %s",
            (cutoff,),
            fetch=False
        )
        logger.info(f"Deleted enriched alerts: {alerts_result if alerts_result else 'completed'}")
        
        # Vacuum to reclaim space (if superuser)
        try:
            execute("VACUUM FULL alerts", fetch=False)
            execute("VACUUM FULL raw_alerts", fetch=False)
            logger.info("Database vacuum completed")
        except Exception as vacuum_error:
            logger.warning(f"Vacuum operation failed (may require superuser): {vacuum_error}")
        
        logger.info(f"Cleanup completed successfully: removed alerts older than {retention_days} days")
        
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise

def perform_vacuum():
    """Standalone vacuum operation for database maintenance"""
    logger.info("Starting database vacuum operation")
    
    try:
        # Vacuum main tables to reclaim space and update statistics
        execute("VACUUM ANALYZE alerts", fetch=False)
        execute("VACUUM ANALYZE raw_alerts", fetch=False)
        execute("VACUUM ANALYZE users", fetch=False)
        logger.info("Database vacuum completed successfully")
        
    except Exception as e:
        logger.warning(f"Database vacuum failed (may require superuser): {e}")

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run cleanup
    try:
        logger.info("Retention worker started")
        cleanup_old_alerts()
        logger.info("Retention worker completed successfully")
    except Exception as e:
        logger.error(f"Retention worker failed: {e}")
        raise
