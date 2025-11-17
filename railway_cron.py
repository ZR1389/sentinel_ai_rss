#!/usr/bin/env python3
"""
Railway Cron Job Script
- Environment bootstrapping for Railway cron one-off tasks
- Maintenance: retention cleanup and vacuum
- Ingestion/Enrichment runners: RSS, Threat Engine, GDELT enrichment, ACLED
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
    
    # Add app directory to Python path
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')
    
    # Setup basic logging for cron job
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger('railway_cron')
    
    # Check critical environment variables
    required_vars = ['DATABASE_URL']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        logger.info("Available environment variables:")
        for key, value in os.environ.items():
            if any(keyword in key.upper() for keyword in ['DATABASE', 'DB', 'URL', 'RAILWAY']):
                logger.info(f"  {key}={'*' * len(value) if 'KEY' in key or 'SECRET' in key or 'PASSWORD' in key else value}")
        
        # Try to load from potential config sources
        logger.info("Trying alternative configuration sources...")
        return False
    
    # Set a flag to indicate cron environment for fallback logic
    os.environ['RAILWAY_CRON_MODE'] = 'true'
    
    logger.info("Environment setup completed successfully")
    return True

def run_retention_cleanup():
    """Run the retention cleanup with proper error handling"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        # Import and run retention worker
        from retention_worker import cleanup_old_alerts
        
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
        from retention_worker import perform_vacuum
        
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
    try:
        from rss_processor import ingest_all_feeds_to_db
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
        logger.info("RSS ingestion completed", extra={"result": res})
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
        from threat_engine import enrich_and_store_alerts
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
        logger.info("ACLED collection completed", extra=result)
        return ok
    except Exception as e:
        logger.error(f"ACLED collection failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False
    except Exception as e:
        logger.error(f"Database vacuum failed: {e}")
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
        elif operation in ("gdelt_enrich", "gdelt-enrich", "gdelt"):
            success = run_gdelt_enrich_once()
        elif operation == "acled":
            success = run_acled_collect()
        else:
            print(f"Unknown operation: {operation}")
            print("Usage: python railway_cron.py [cleanup|vacuum|rss|engine|gdelt_enrich|acled]")
            sys.exit(1)
    else:
        # Default to cleanup
        success = run_retention_cleanup()
    
    sys.exit(0 if success else 1)
