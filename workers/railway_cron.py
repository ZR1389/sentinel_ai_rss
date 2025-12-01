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
    
    # Add app directory to Python path
    if '/app' not in sys.path:
        sys.path.insert(0, '/app')
    
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
        return False
    except Exception as e:
        logger.error(f"ACLED collection failed: {e}")
        return False

# GDELT and ACLED functions removed - no longer used in the system

def run_proximity_check():
    """Check all travelers for nearby threats"""
    
    logger = logging.getLogger('railway_cron')
    
    try:
        from proximity_alerts import check_all_travelers
        
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
    """Geocode missing coordinates in alerts using city_utils"""
    
    logger = logging.getLogger('railway_cron')
    
    # Country capital cities for fallback when only country is known
    COUNTRY_CAPITALS = {
        'united kingdom': ('London', 51.5074, -0.1278),
        'united states': ('Washington DC', 38.9072, -77.0369),
        'india': ('New Delhi', 28.6139, 77.2090),
        'australia': ('Canberra', -35.2809, 149.1300),
        'brazil': ('Brasilia', -15.7801, -47.9292),
        'sri lanka': ('Colombo', 6.9271, 79.8612),
        'nigeria': ('Abuja', 9.0579, 7.4951),
        'iraq': ('Baghdad', 33.3152, 44.3661),
        'israel': ('Jerusalem', 31.7683, 35.2137),
        'syria': ('Damascus', 33.5138, 36.2765),
        'lebanon': ('Beirut', 33.8938, 35.5018),
        'pakistan': ('Islamabad', 33.6844, 73.0479),
        'afghanistan': ('Kabul', 34.5553, 69.2075),
        'iran': ('Tehran', 35.6892, 51.3890),
        'russia': ('Moscow', 55.7558, 37.6173),
        'china': ('Beijing', 39.9042, 116.4074),
        'japan': ('Tokyo', 35.6762, 139.6503),
        'south korea': ('Seoul', 37.5665, 126.9780),
        'germany': ('Berlin', 52.5200, 13.4050),
        'france': ('Paris', 48.8566, 2.3522),
        'italy': ('Rome', 41.9028, 12.4964),
        'spain': ('Madrid', 40.4168, -3.7038),
        'turkey': ('Ankara', 39.9334, 32.8597),
        'egypt': ('Cairo', 30.0444, 31.2357),
        'south africa': ('Pretoria', -25.7479, 28.2293),
        'kenya': ('Nairobi', -1.2921, 36.8219),
        'ethiopia': ('Addis Ababa', 9.0320, 38.7469),
        'mexico': ('Mexico City', 19.4326, -99.1332),
        'canada': ('Ottawa', 45.4215, -75.6972),
    }
    
    try:
        from utils.city_utils import get_city_coords
        from utils.db_utils import _get_db_connection
        from utils.geocoding_monitor import check_and_notify
        
        logger.info("Starting geocode backfill for alerts with city/country...")
        
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            # Find alerts with city/country but no coordinates
            cur.execute('''
                SELECT id, city, country 
                FROM alerts 
                WHERE (latitude IS NULL OR longitude IS NULL) 
                AND city IS NOT NULL 
                AND country IS NOT NULL
                LIMIT 200
            ''')
            rows = cur.fetchall()
            
            logger.info(f"Found {len(rows)} alerts with city to geocode")
            
            updated = 0
            for row in rows:
                alert_id, city, country = row
                lat, lon = get_city_coords(city, country)
                if lat is not None and lon is not None:
                    cur.execute('''
                        UPDATE alerts SET latitude = %s, longitude = %s, location_sharing = true
                        WHERE id = %s
                    ''', (lat, lon, alert_id))
                    updated += 1
            
            conn.commit()
            logger.info(f"Updated {updated} alerts with coordinates (city-based)")
        
        # Now geocode alerts with ONLY country (no city) using capitals
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            cur.execute('''
                SELECT id, country 
                FROM alerts 
                WHERE (latitude IS NULL OR longitude IS NULL) 
                AND (city IS NULL OR city = '')
                AND country IS NOT NULL
                LIMIT 200
            ''')
            rows = cur.fetchall()
            
            logger.info(f"Found {len(rows)} alerts with country-only to geocode")
            
            updated = 0
            for row in rows:
                alert_id, country = row
                country_lower = (country or '').lower().strip()
                if country_lower in COUNTRY_CAPITALS:
                    capital, lat, lon = COUNTRY_CAPITALS[country_lower]
                    cur.execute('''
                        UPDATE alerts SET latitude = %s, longitude = %s, city = %s, location_sharing = true
                        WHERE id = %s
                    ''', (lat, lon, capital, alert_id))
                    updated += 1
            
            conn.commit()
            logger.info(f"Updated {updated} alerts with coordinates (country capital fallback)")
        
        # Also geocode raw_alerts if they have city/country
        logger.info("Starting geocode backfill for raw_alerts with city/country...")
        
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            cur.execute('''
                SELECT id, city, country 
                FROM raw_alerts 
                WHERE (latitude IS NULL OR longitude IS NULL) 
                AND city IS NOT NULL 
                AND country IS NOT NULL
                LIMIT 200
            ''')
            rows = cur.fetchall()
            
            logger.info(f"Found {len(rows)} raw_alerts to geocode")
            
            updated = 0
            for row in rows:
                alert_id, city, country = row
                lat, lon = get_city_coords(city, country)
                if lat is not None and lon is not None:
                    cur.execute('''
                        UPDATE raw_alerts SET latitude = %s, longitude = %s
                        WHERE id = %s
                    ''', (lat, lon, alert_id))
                    updated += 1
            
            conn.commit()
            logger.info(f"Updated {updated} raw_alerts with coordinates")
        
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
        from email_dispatcher import send_pdf_report
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
    
    logger = logging.getLogger('railway_cron')
    
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
