# retention_worker.py - Run as Railway background worker
import os
from datetime import datetime, timedelta, timezone
from db_utils import execute

# Structured logging setup
from logging_config import setup_logging, get_logger, get_metrics_logger

setup_logging("retention-worker")
logger = get_logger("retention_worker")
metrics = get_metrics_logger("retention_worker")

def cleanup_old_alerts():
    """Delete alerts older than retention period"""
    retention_days = int(os.getenv("ALERT_RETENTION_DAYS", "90"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    
    logger.info("retention_cleanup_started", 
               retention_days=retention_days, 
               cutoff_date=cutoff.isoformat())
    
    start_time = datetime.now()
    
    try:
        # Delete raw alerts first (older than enriched)
        raw_start = datetime.now()
        execute("DELETE FROM raw_alerts WHERE published < %s", (cutoff,))
        raw_duration = (datetime.now() - raw_start).total_seconds() * 1000
        
        metrics.database_operation(
            operation="delete",
            table="raw_alerts",
            duration_ms=round(raw_duration, 2),
            rows_affected=None  # execute doesn't return row count
        )
        
        # Then delete enriched alerts
        alerts_start = datetime.now()
        execute("DELETE FROM alerts WHERE published < %s", (cutoff,))
        alerts_duration = (datetime.now() - alerts_start).total_seconds() * 1000
        
        metrics.database_operation(
            operation="delete",
            table="alerts",
            duration_ms=round(alerts_duration, 2),
            rows_affected=None  # execute doesn't return row count
        )
        
        # Vacuum to reclaim space (if superuser)
        try:
            vacuum_start = datetime.now()
            
            # Import raw database connection for VACUUM (needs autocommit)
            from db_utils import _get_db_connection
            
            with _get_db_connection() as conn:
                conn.set_session(autocommit=True)
                with conn.cursor() as cur:
                    cur.execute("VACUUM FULL alerts")
                    cur.execute("VACUUM FULL raw_alerts")
            
            vacuum_duration = (datetime.now() - vacuum_start).total_seconds() * 1000
            logger.info("database_vacuum_completed", 
                       duration_ms=round(vacuum_duration, 2))
        except Exception as vacuum_error:
            logger.warning("database_vacuum_failed", 
                          error=str(vacuum_error),
                          reason="vacuum_requires_autocommit_or_superuser")
        
        total_duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info("retention_cleanup_completed",
                   retention_days=retention_days,
                   total_duration_ms=round(total_duration, 2))
        
    except Exception as e:
        logger.error("retention_cleanup_failed", error=str(e))
        raise

def perform_vacuum():
    """Standalone vacuum operation for database maintenance"""
    logger.info("database_vacuum_started")
    
    try:
        # Import raw database connection for VACUUM (needs autocommit)
        from db_utils import _get_db_connection
        
        # VACUUM must run outside transaction block
        with _get_db_connection() as conn:
            conn.set_session(autocommit=True)
            with conn.cursor() as cur:
                cur.execute("VACUUM ANALYZE alerts")
                cur.execute("VACUUM ANALYZE raw_alerts") 
                cur.execute("VACUUM ANALYZE users")
        
        logger.info("database_vacuum_completed")
        
    except Exception as e:
        logger.warning("database_vacuum_failed", 
                      error=str(e),
                      reason="vacuum_requires_autocommit_or_superuser")

if __name__ == "__main__":    
    # Run cleanup
    try:
        logger.info("retention_worker_started")
        cleanup_old_alerts()
        logger.info("retention_worker_completed")
    except Exception as e:
        logger.error("retention_worker_failed", error=str(e))
        raise
