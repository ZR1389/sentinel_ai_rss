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
        raw_result = execute(
            "DELETE FROM raw_alerts WHERE published < %s",
            (cutoff,),
            fetch=False
        )
        raw_duration = (datetime.now() - raw_start).total_seconds() * 1000
        
        metrics.database_operation(
            operation="delete",
            table="raw_alerts",
            duration_ms=round(raw_duration, 2),
            rows_affected=raw_result if raw_result else 0
        )
        
        # Then delete enriched alerts
        alerts_start = datetime.now()
        alerts_result = execute(
            "DELETE FROM alerts WHERE published < %s",
            (cutoff,),
            fetch=False
        )
        alerts_duration = (datetime.now() - alerts_start).total_seconds() * 1000
        
        metrics.database_operation(
            operation="delete",
            table="alerts",
            duration_ms=round(alerts_duration, 2),
            rows_affected=alerts_result if alerts_result else 0
        )
        
        # Vacuum to reclaim space (if superuser)
        try:
            vacuum_start = datetime.now()
            execute("VACUUM FULL alerts", fetch=False)
            execute("VACUUM FULL raw_alerts", fetch=False)
            vacuum_duration = (datetime.now() - vacuum_start).total_seconds() * 1000
            
            logger.info("database_vacuum_completed", 
                       duration_ms=round(vacuum_duration, 2))
        except Exception as vacuum_error:
            logger.warning("database_vacuum_failed", 
                          error=str(vacuum_error),
                          reason="may_require_superuser")
        
        total_duration = (datetime.now() - start_time).total_seconds() * 1000
        logger.info("retention_cleanup_completed",
                   retention_days=retention_days,
                   raw_alerts_deleted=raw_result if raw_result else 0,
                   alerts_deleted=alerts_result if alerts_result else 0,
                   total_duration_ms=round(total_duration, 2))
        
    except Exception as e:
        logger.error("retention_cleanup_failed", error=str(e))
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
    # Run cleanup
    try:
        logger.info("retention_worker_started")
        cleanup_old_alerts()
        logger.info("retention_worker_completed")
    except Exception as e:
        logger.error("retention_worker_failed", error=str(e))
        raise
