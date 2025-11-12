# retention_worker.py - Run as Railway background worker
import os
import sys
from datetime import datetime, timedelta, timezone

# Ensure we can find environment variables
def load_environment():
    """Load environment variables for Railway deployment"""
    # Railway automatically provides DATABASE_URL in the environment
    # But for cron jobs, we need to ensure the environment is properly loaded
    
    if not os.getenv("DATABASE_URL"):
        # Try to load from various sources
        env_sources = [
            "/app/.env",  # Railway app directory
            ".env",       # Current directory
        ]
        
        for env_file in env_sources:
            if os.path.exists(env_file):
                try:
                    with open(env_file, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#') and '=' in line:
                                key, value = line.split('=', 1)
                                if key == "DATABASE_URL" and not os.getenv(key):
                                    os.environ[key] = value
                                    break
                except Exception:
                    continue
    
    # Final check
    if not os.getenv("DATABASE_URL"):
        print("ERROR: DATABASE_URL not found in environment or .env files")
        print("Available environment variables:", [k for k in os.environ.keys() if 'DATABASE' in k.upper()])
        sys.exit(1)

# Load environment before importing db_utils
load_environment()

from db_utils import execute

# Structured logging setup with fallback
try:
    from logging_config import setup_logging, get_logger, get_metrics_logger
    setup_logging("retention-worker")
    logger = get_logger("retention_worker")
    metrics = get_metrics_logger("retention_worker")
except ImportError:
    # Fallback to basic logging if logging_config is not available
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("retention_worker")
    
    # Create a simple metrics mock
    class MockMetrics:
        def database_operation(self, **kwargs):
            logger.info(f"Database operation: {kwargs}")
    metrics = MockMetrics()

def cleanup_old_alerts():
    """Delete alerts older than retention period"""
    from config import CONFIG
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=CONFIG.app.alert_retention_days)
    
    logger.info("retention_cleanup_started", 
               retention_days=CONFIG.app.alert_retention_days, 
               cutoff_date=cutoff.isoformat())
    
    start_time = datetime.now()
    
    try:
        # Verify database connection first
        try:
            from db_utils import _get_db_connection
            with _get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            logger.info("database_connection_verified")
        except Exception as conn_error:
            logger.error("database_connection_failed", 
                        error=str(conn_error),
                        database_url_set=bool(os.getenv("DATABASE_URL")))
            raise
        
        # Delete raw alerts first (older than enriched)
        raw_start = datetime.now()
        try:
            execute("DELETE FROM raw_alerts WHERE published < %s", (cutoff,))
            raw_duration = (datetime.now() - raw_start).total_seconds() * 1000
            
            metrics.database_operation(
                operation="delete",
                table="raw_alerts",
                duration_ms=round(raw_duration, 2),
                rows_affected=None  # execute doesn't return row count
            )
            logger.info("raw_alerts_cleanup_completed", duration_ms=round(raw_duration, 2))
        except Exception as raw_error:
            logger.error("raw_alerts_cleanup_failed", error=str(raw_error))
            # Continue with alerts cleanup even if raw_alerts fails
        
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
        logger.info("alerts_cleanup_completed", duration_ms=round(alerts_duration, 2))
        
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
                   retention_days=CONFIG.app.alert_retention_days,
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
