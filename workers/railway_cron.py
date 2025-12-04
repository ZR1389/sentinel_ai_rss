#!/usr/bin/env python3
"""
Railway Cron Job Script
- Environment bootstrapping for Railway cron one-off tasks
- Maintenance: retention cleanup and vacuum
- Ingestion/Enrichment runners: RSS, Threat Engine only
"""

import os
import sys
import logging
import asyncio

def setup_cron_environment():
    """Setup environment for Railway cron job execution"""
    
    # Set working directory to app directory
    if os.path.exists('/app'):
        os.chdir('/app')
    else:
        # For local testing: change to parent directory (root of project)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)  # Go up from workers/ to root
        os.chdir(project_root)
    
    # Add app directory to Python path
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')
    
    # For local testing: add current working directory to path
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    
    # Setup basic logging for cron job
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger('railway_cron')

    # Normalize env so DATABASE_URL is available where modules expect it
    try:
        # Import after sys.path adjustments
        from utils.env_utils import bootstrap_runtime_env
        bootstrap_runtime_env()
    except Exception as e:
        logger.warning(f"Env bootstrap skipped: {e}")

    # Verify we have a usable DB URL via either DATABASE_URL or DATABASE_PUBLIC_URL
    db_url = os.getenv('DATABASE_URL') or os.getenv('DATABASE_PUBLIC_URL')
    if not db_url:
        logger.error("Missing required environment variables: ['DATABASE_URL' or 'DATABASE_PUBLIC_URL']")
        logger.info("Available environment variables:")
        for key, value in os.environ.items():
            if any(keyword in key.upper() for keyword in ['DATABASE', 'DB', 'URL', 'RAILWAY']):
                redacted = value
                if isinstance(value, str) and '://' in value and '@' in value:
                    try:
                        scheme, rest = value.split('://', 1)
                        host_part = rest.split('@', 1)[1]
                        redacted = f"{scheme}://***@{host_part}"
                    except Exception:
                        redacted = '***'
                logger.info(f"  {key}={redacted}")
        return False
    else:
        # Log effective DB URL masked
        if '://' in db_url and '@' in db_url:
            try:
                scheme, rest = db_url.split('://', 1)
                host_part = rest.split('@', 1)[1]
                masked = f"{scheme}://***@{host_part}"
            except Exception:
                masked = '***'
        else:
            masked = db_url
        logger.info(f"Effective DATABASE_URL resolved: {masked}")
    
    # Set a flag to indicate cron environment for fallback logic
    os.environ['RAILWAY_CRON_MODE'] = 'true'
    
    logger.info("Environment setup completed successfully")
    return True

def run_retention_cleanup():
    """Run the retention cleanup with proper error handling"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        # Import and run retention worker
        from workers.retention_worker import cleanup_old_alerts
        
        logger.info("Starting retention cleanup...")
        cleanup_old_alerts()
        logger.info("Retention cleanup completed successfully")
        return True
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure retention_worker.py is available in the current directory")
        return False
    except Exception as e:
        logger.error(f"Retention cleanup failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def run_vacuum():
    """Run database vacuum with proper error handling"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        # Import and run vacuum
        from workers.retention_worker import perform_vacuum
        
        logger.info("Starting database vacuum...")
        perform_vacuum()
        logger.info("Database vacuum completed successfully")
        return True
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return False

def run_rss_ingest():
    """Run RSS ingestion into raw_alerts with proper loop handling"""
    logger = logging.getLogger('railway_cron')
    
    # Critical environment checks
    logger.info("=" * 60)
    logger.info("RSS INGESTION STARTUP CHECKS")
    logger.info("=" * 60)
    
    db_url = os.getenv("DATABASE_URL")
    logger.info(f"DATABASE_URL: {'SET' if db_url else 'MISSING'}")
    logger.info(f"RSS_WRITE_TO_DB: {os.getenv('RSS_WRITE_TO_DB', 'not set')}")
    logger.info(f"RSS_DEBUG: {os.getenv('RSS_DEBUG', 'not set')}")
    logger.info(f"RSS_STRICT_FILTER: {os.getenv('RSS_STRICT_FILTER', 'not set')}")
    logger.info(f"RSS_ALLOWED_LANGS: {os.getenv('RSS_ALLOWED_LANGS', 'not set')}")
    
    if not db_url:
        logger.error("FATAL: DATABASE_URL is not set! Cannot proceed with RSS ingestion.")
        logger.error("Set DATABASE_URL in your Railway service environment variables.")
        return False
    
    logger.info("=" * 60)
    
    try:
        from services.rss_processor import ingest_all_feeds_to_db
    except Exception as e:
        logger.error(f"Import error (rss_processor): {e}")
        return False

    try:
        limit = int(os.getenv("RSS_BATCH_LIMIT", "400"))
        groups_env = os.getenv("RSS_GROUPS", "")
        groups = [g.strip() for g in groups_env.split(",") if g.strip()] or None

        logger.info("Starting RSS ingestion", extra={"limit": limit, "groups": groups})
        # Ensure we have an event loop (cron one-off process)
        try:
            res = asyncio.get_event_loop().run_until_complete(
                ingest_all_feeds_to_db(group_names=groups, limit=limit, write_to_db=True)
            )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            res = loop.run_until_complete(
                ingest_all_feeds_to_db(group_names=groups, limit=limit, write_to_db=True)
            )
            loop.close()
        
        logger.info("=" * 60)
        logger.info("RSS INGESTION COMPLETED")
        logger.info("=" * 60)
        logger.info(f"Alerts processed: {res.get('alerts_processed', 0)}")
        logger.info(f"Feeds processed: {res.get('feeds_processed', 0)}")
        logger.info(f"Written to DB: {res.get('written_to_db', 0)}")
        if 'error' in res:
            logger.error(f"Error: {res['error']}")
        logger.info("=" * 60)
        
        return True
    except Exception as e:
        logger.error(f"RSS ingestion failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def run_engine_enrich():
    """Run Threat Engine to enrich raw_alerts into alerts"""
    logger = logging.getLogger('railway_cron')
    try:
        from services.threat_engine import enrich_and_store_alerts
    except Exception as e:
        logger.error(f"Import error (threat_engine): {e}")
        return False

    try:
        limit = int(os.getenv("ENGINE_BATCH_LIMIT", "1000"))
        region = os.getenv("ENGINE_FILTER_REGION") or None
        country = os.getenv("ENGINE_FILTER_COUNTRY") or None
        city = os.getenv("ENGINE_FILTER_CITY") or None
        logger.info("Starting Threat Engine enrichment", extra={"limit": limit, "region": region, "country": country, "city": city})
        enriched = enrich_and_store_alerts(region=region, country=country, city=city, limit=limit)
        logger.info("Threat Engine enrichment completed", extra={"count": len(enriched or [])})
        return True
    except Exception as e:
        logger.error(f"Threat Engine enrichment failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def run_gdelt_enrich_once():
    """Process pending GDELT events into alerts (one-off batches until drained or cap)."""
    logger = logging.getLogger('railway_cron')
    try:
        from gdelt_enrichment_worker import get_conn, process_batch
    except Exception as e:
        logger.error(f"Import error (gdelt_enrichment_worker): {e}")
        return False

    try:
        batch_size = int(os.getenv("GDELT_ENRICHMENT_BATCH_SIZE", "1000"))
        max_batches = int(os.getenv("GDELT_ENRICHMENT_MAX_BATCHES", "100"))
        total = 0
        conn = get_conn()
        for _ in range(max_batches):
            processed = process_batch(conn, min(batch_size, 1000))
            total += processed
            if processed == 0:
                break
        try:
            conn.close()
        except Exception:
            pass
        logger.info("GDELT enrichment completed", extra={"processed": total, "batches": max_batches})
        return True
    except Exception as e:
        logger.error(f"GDELT enrichment failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def run_acled_collect():
    """Run ACLED collector and persist to raw_alerts"""
    logger = logging.getLogger('railway_cron')
    try:
        from acled_collector import run_acled_collector
    except Exception as e:
        logger.error(f"Import error (acled_collector): {e}")
        return False

    try:
        countries_env = os.getenv("ACLED_COUNTRIES", "")
        countries = [c.strip() for c in countries_env.split(",") if c.strip()] if countries_env else None
        days_back = min(int(os.getenv("ACLED_DAYS_BACK", "1")), 7)
        logger.info("Starting ACLED collection", extra={"countries": countries or 'default', "days_back": days_back})
        result = run_acled_collector(countries=countries, days_back=days_back)
        ok = bool(result.get("success"))
        return ok
    except Exception as e:
        logger.error(f"ACLED collection failed: {e}", exc_info=True)
        return False

# GDELT and ACLED functions removed - no longer used in the system

def run_proximity_check():
    """Check all travelers for nearby threats"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        from utils.proximity_alerts import check_all_travelers
        
        logger.info("Starting proximity check for all travelers...")
        result = check_all_travelers(send_alerts=True)
        
        if 'error' in result:
            logger.error(f"Proximity check failed: {result['error']}")
            return False
        
        logger.info(f"Proximity check completed: {result}")
        return True
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return False
    except Exception as e:
        logger.error(f"Proximity check failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def run_geocode_backfill():
    """Geocode missing coordinates in raw_alerts"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        from services.geocoding_service import geocode_and_update_table
        from utils.geocoding_monitor import check_and_notify
        
        # Geocode raw_alerts first (most recent data)
        logger.info("Starting geocode backfill for raw_alerts...")
        geocode_and_update_table(
            table_name='raw_alerts',
            id_column='id',
            location_column='location',
            limit=100  # Process 100 rows per run
        )
        
        # Optionally geocode alerts table too
        logger.info("Starting geocode backfill for alerts...")
        geocode_and_update_table(
            table_name='alerts',
            id_column='id',
            location_column='location',
            limit=50  # Fewer for alerts since it's larger
        )
        
        # Check and notify if backlog is cleared
        try:
            notify_result = check_and_notify()
            if notify_result.get('notified'):
                logger.info(f"Backlog cleared notification sent via: {notify_result.get('channels')}")
        except Exception as e:
            logger.warning(f"Geocoding monitor check failed: {e}")
        
        logger.info("Geocode backfill completed successfully")
        return True
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return False
    except Exception as e:
        logger.error(f"Geocode backfill failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def run_scheduler_notify():
    """Send daily email PDF reports to eligible users"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        from utils.email_dispatcher import send_pdf_report
        import psycopg2
        from psycopg2.extras import DictCursor
        
        logger.info("Starting scheduler notify (email PDF reports)...")
        
        # Get database connection
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("DATABASE_URL not set")
            return False
        
        # Email job: send PDF reports
        try:
            conn = psycopg2.connect(db_url, cursor_factory=DictCursor)
            cur = conn.cursor()
            cur.execute("""
                SELECT u.email, u.plan, u.region
                FROM users u
                JOIN plans p ON u.plan = p.name
                WHERE COALESCE(p.pdf_reports_per_month, 0) > 0
                  AND u.is_active = TRUE
            """)
            pdf_users = cur.fetchall()
            cur.close()
            conn.close()
            
            logger.info(f"Found {len(pdf_users)} users eligible for PDF reports")
            for user in pdf_users:
                email = user["email"]
                region = user.get("region")
                result = send_pdf_report(email=email, region=region)
                status = result.get("status", "unknown")
                if status == "sent":
                    logger.info(f"PDF report sent to {email}")
                elif status == "skipped":
                    logger.info(f"PDF report skipped for {email}: {result.get('reason', '')}")
                elif status == "error":
                    logger.warning(f"PDF report error for {email}: {result.get('reason', '')}")
        except Exception as e:
            logger.error(f"Email job failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Telegram alerts removed - send_alerts_to_telegram function doesn't exist
        # Telegram notifications should be triggered via proximity_alerts.py instead
        
        logger.info("Scheduler notify completed")
        return True
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return False
    except Exception as e:
        logger.error(f"Scheduler notify failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    # Setup environment
    if not setup_cron_environment():
        sys.exit(1)
    
    # Determine what operation to run based on command line argument
    if len(sys.argv) > 1:
        operation = sys.argv[1]
        
        if operation == "cleanup":
            success = run_retention_cleanup()
        elif operation == "vacuum":
            success = run_vacuum()
        elif operation == "rss":
            success = run_rss_ingest()
        elif operation == "engine":
            success = run_engine_enrich()
        # GDELT and ACLED removed - no longer used
        elif operation == "proximity":
            success = run_proximity_check()
        elif operation == "geocode":
            success = run_geocode_backfill()
        elif operation == "notify":
            success = run_scheduler_notify()
        elif operation in ("trial_reminders", "check_trials"):
            logger = logging.getLogger('railway_cron')
            logger.warning(f"Operation '{operation}' not implemented yet")
            success = True
        else:
            print(f"Unknown operation: {operation}")
            print("Usage: python railway_cron.py [cleanup|vacuum|rss|engine|gdelt_enrich|acled|proximity|geocode|notify|trial_reminders|check_trials]")
            sys.exit(1)
    else:
        # Default to cleanup
        success = run_retention_cleanup()
    
    sys.exit(0 if success else 1)
