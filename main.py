
# main.py — Sentinel AI App API (JWT-guarded) • v2025-08-13
from __future__ import annotations
import os
from dotenv import load_dotenv

# Load .env.dev if present (for local dev), otherwise fall back to .env
if os.path.exists('.env.dev'):
    load_dotenv('.env.dev', override=True)
else:
    load_dotenv()

# Notes:
# - Only /chat counts toward plan usage, and only AFTER a successful advisory.
# - /rss/run and /engine/run are backend ops and are NOT metered.
# - Newsletter is UNMETERED; requires verified login.
# - PDF/Email/Push/Telegram are UNMETERED but require a PAID plan.
# - Auth/verification endpoints added and left unmetered.
# - Profile endpoints added: /profile/me (GET), /profile/update (POST).

import os
import logging
import traceback
import base64
import signal
import time
from typing import Any, Dict, Optional, Callable
from datetime import datetime
from functools import wraps
import time
import uuid
try:
    from fallback_jobs import (
        submit_fallback_job,
        get_fallback_job_status,
        list_fallback_jobs,
        job_queue_enabled,
    )
except Exception:
    submit_fallback_job = get_fallback_job_status = list_fallback_jobs = job_queue_enabled = None

from flask import Flask, request, jsonify, make_response, g, render_template

# Rate limiting (optional)
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception:
    Limiter = None
    get_remote_address = None


from map_api import map_api
from webpush_endpoints import webpush_bp
try:
    from app.routes.socmint_routes import socmint_bp, set_socmint_limiter
except ImportError:
    from socmint_routes import socmint_bp, set_socmint_limiter

# Initialize logging early (before any logger usage)
from logging_config import get_logger, get_metrics_logger, setup_logging
setup_logging("sentinel-api")
logger = get_logger("sentinel.main")
metrics = get_metrics_logger("sentinel.main")
from cache_utils import HybridCache

app = Flask(__name__)
app.register_blueprint(map_api)
app.register_blueprint(webpush_bp)
app.register_blueprint(socmint_bp, url_prefix='/api/socmint')
# Start trends snapshotter (background) if enabled
try:
    from metrics_trends import start_trends_snapshotter
    start_trends_snapshotter()
except Exception as e:
    pass

# Ensure PostGIS extension is installed (needed for geocoding)
try:
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        conn = psycopg2.connect(db_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cur.execute("SELECT PostGIS_Version();")
        version = cur.fetchone()
        if version:
            logger.info(f"✓ PostGIS ready: {version[0]}")
        cur.close()
        conn.close()
except Exception as e:
    logger.warning(f"[main] PostGIS check/install: {e}")

# Start GDELT polling thread if enabled
if os.getenv('GDELT_ENABLED', 'false').lower() == 'true':
    try:
        from gdelt_ingest import start_gdelt_polling
        start_gdelt_polling()
        logger.info("✓ GDELT polling started")
    except Exception as e:
        logger.warning(f"[main] GDELT polling not started: {e}")
else:
    logger.info("[main] GDELT polling disabled (GDELT_ENABLED not set)")

# Apply socmint rate limits post-registration to avoid circular import issues
if 'Limiter' in globals() and Limiter and get_remote_address:
    try:
        # Initialize limiter if not already
        limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"], storage_uri="memory://")
        set_socmint_limiter(limiter)
    except Exception as e:
        logger.warning(f"[main] Could not initialize limiter or apply socmint limits: {e}")

# Hybrid caches: Redis-backed with in-process fallback for map endpoints
_MAP_CACHE = HybridCache(prefix="map", maxsize=2048)
_AGG_CACHE = HybridCache(prefix="agg", maxsize=1024)# ---------- Global Error Handlers ----------
@app.errorhandler(500)
def handle_500_error(e):
    import traceback
    logger.error("server_error_500",
                url=request.url,
                method=request.method,
                headers=dict(request.headers),
                error=str(e),
                traceback=traceback.format_exc())
    return jsonify({"error": "Internal server error", "details": str(e)}), 500

# ---------- Input validation ----------
from validation import validate_alert_batch, validate_enrichment_data

# ---------- CORS (more restrictive default) ----------
# Import centralized configuration
from config import CONFIG

# Default: production frontends only — override with comma-separated env var if needed
ALLOWED_ORIGINS = [o.strip() for o in CONFIG.app.allowed_origins.split(",") if o.strip()]

def _build_cors_response(resp):
    origin = request.headers.get("Origin")
    # If ALLOWED_ORIGINS contains "*" or exact origin, echo it; otherwise omit header
    if "*" in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    elif origin and origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
    # else: do not set Access-Control-Allow-Origin to avoid accidental permissive CORS
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-User-Email, Authorization, If-Match, If-None-Match"
    resp.headers["Access-Control-Expose-Headers"] = "ETag, Last-Modified, X-Version, Cache-Control"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

@app.after_request
def _after(resp):
    return _build_cors_response(resp)

@app.route("/_options", methods=["OPTIONS"])
def _options_only():
    return _build_cors_response(make_response("", 204))

# ---------- Health Check Endpoints for Railway ----------
@app.route("/health", methods=["GET"])
def health_check():
    """Comprehensive health check for Railway zero-downtime deployments."""
    try:
        from health_check import perform_health_check
        health_data = perform_health_check()
        # Attach public base URL for easy discovery (env or request-derived)
        try:
            base_url = (CONFIG.app.public_base_url or request.url_root).rstrip("/")
            health_data["base_url"] = base_url
        except Exception:
            pass
        status_code = 200  # Always return 200 for Railway compatibility
        return make_response(jsonify(health_data), status_code)
    except Exception as e:
        return make_response(jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500)

@app.route("/health/quick", methods=["GET"])  
def health_quick():
    """Quick health check - database only."""
    try:
        from health_check import check_database_health
        db_check = check_database_health()
        status = "healthy" if db_check["connected"] else "degraded"
        return jsonify({"status": status, "database": db_check})
    except Exception as e:
        return make_response(jsonify({"status": "error", "error": str(e)}), 500)

@app.route("/ping", methods=["GET"])
def ping():
    """Simple liveness probe."""
    return jsonify({"status": "ok", "message": "pong"})

# ---------- Auth status (server-friendly) ----------
@app.route("/auth/status", methods=["GET"])  # returns auth context from Bearer token
def auth_status():
    try:
        from auth_utils import decode_token
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return _build_cors_response(make_response(jsonify({"error": "Unauthorized"}), 401))
        token = auth.split(" ", 1)[1].strip()
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            return _build_cors_response(make_response(jsonify({"error": "Invalid or expired token"}), 401))

        email = payload.get("user_email")
        plan_name = (payload.get("plan") or os.getenv("DEFAULT_PLAN", "FREE")).strip().upper()

        # Resolve usage + full feature limits
        chat_used = 0
        all_limits = {}
        plan_features = {}
        try:
            from plan_utils import get_usage, get_plan_limits
            from config.plans import get_plan_feature
            u = get_usage(email) if get_usage else None
            if isinstance(u, dict):
                chat_used = int(u.get("chat_messages_used", 0))

            # Get all plan limits (chat + feature access)
            all_limits = get_plan_limits(email) or {}
            
            # Get full plan features from plans.py
            plan_features = {
                "chat_messages_lifetime": get_plan_feature(plan_name, "chat_messages_lifetime"),
                "conversation_threads": get_plan_feature(plan_name, "conversation_threads"),
                "messages_per_thread": get_plan_feature(plan_name, "messages_per_thread"),
                "trip_planner_destinations": get_plan_feature(plan_name, "trip_planner_destinations"),
                "saved_searches": get_plan_feature(plan_name, "saved_searches"),
                "email_alerts": get_plan_feature(plan_name, "email_alerts", False),
                "sms_alerts": get_plan_feature(plan_name, "sms_alerts", False),
                "geofenced_alerts": get_plan_feature(plan_name, "geofenced_alerts", False),
                "route_analysis": get_plan_feature(plan_name, "route_analysis", False),
                "briefing_packages": get_plan_feature(plan_name, "briefing_packages", False),
            }
        except Exception as e:
            logger.warning("Failed to resolve usage in /auth/status: %s", e)
            all_limits = {"chat_messages_per_month": 3, "alerts_days": 7, "alerts_max_results": 30}

        return _build_cors_response(jsonify({
            "email": email,
            "plan": plan_name,
            "email_verified": True,
            "usage": {
                "chat_messages_used": chat_used,
                "chat_messages_limit": all_limits.get("chat_messages_per_month", 3),
            },
            "limits": {
                "alerts_days": all_limits.get("alerts_days", 7),
                "alerts_max_results": all_limits.get("alerts_max_results", 30),
                "map_days": all_limits.get("map_days", 7),
                "timeline_days": all_limits.get("timeline_days", 7),
                "statistics_days": all_limits.get("statistics_days", 7),
                "monitoring_days": all_limits.get("monitoring_days", 7),
                "chat_messages_per_month": all_limits.get("chat_messages_per_month", 3),
                # Add detailed plan features
                "chat_messages_lifetime": plan_features.get("chat_messages_lifetime"),
                "conversation_threads": plan_features.get("conversation_threads"),
                "messages_per_thread": plan_features.get("messages_per_thread"),
                "trip_planner_destinations": plan_features.get("trip_planner_destinations"),
                "saved_searches": plan_features.get("saved_searches"),
            },
            "features": {
                "email_alerts": plan_features.get("email_alerts", False),
                "sms_alerts": plan_features.get("sms_alerts", False),
                "geofenced_alerts": plan_features.get("geofenced_alerts", False),
                "route_analysis": plan_features.get("route_analysis", False),
                "briefing_packages": plan_features.get("briefing_packages", False),
            },
        }))
    except Exception as e:
        logger.error(f"/auth/status error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Auth status failed"}), 500))

# ---------- Retention Management Endpoints ----------
@app.route("/admin/retention/status", methods=["GET"])
def retention_status():
    """Check retention worker status and database statistics."""
    try:
        from retention_worker import health_check as retention_health_check
        status = retention_health_check()
        return jsonify(status)
    except Exception as e:
        return make_response(jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500)

@app.route("/admin/retention/cleanup", methods=["POST"])
def manual_retention_cleanup():
    """Manually trigger retention cleanup (admin only)."""
    try:
        # Basic auth check - in production you'd want proper JWT validation
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        from retention_worker import cleanup_old_alerts
        result = cleanup_old_alerts()
        
        return jsonify({
            "status": "success",
            "message": "Retention cleanup completed",
            "result": result,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        
    except Exception as e:
        return make_response(jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500)

@app.route("/admin/migration/apply", methods=["POST"])
def apply_migration_endpoint():
    """Apply database migration (admin only). Useful for deploying schema changes."""
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        data = request.json or {}
        migration_name = data.get("migration")
        
        if not migration_name:
            # List available migrations
            migrations = [f for f in os.listdir("migrations") if f.endswith(".sql")] if os.path.exists("migrations") else []
            return jsonify({
                "error": "No migration specified",
                "usage": "POST with {\"migration\": \"004_travel_risk_itineraries.sql\"}",
                "available_migrations": sorted(migrations)
            }), 400
        
        migration_path = f"migrations/{migration_name}"
        if not os.path.exists(migration_path):
            return jsonify({
                "error": f"Migration not found: {migration_name}",
                "available": sorted([f for f in os.listdir("migrations") if f.endswith(".sql")])
            }), 404
        
        with open(migration_path, 'r') as f:
            migration_sql = f.read()
        
        # Apply via connection pool
        from db_utils import get_connection_pool
        pool = get_connection_pool()
        conn = pool.getconn()
        
        try:
            cur = conn.cursor()
            cur.execute(migration_sql)
            conn.commit()
            logger.info(f"[ADMIN] Migration applied: {migration_name}")
            return jsonify({
                "status": "success",
                "migration": migration_name,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
        except Exception as e:
            conn.rollback()
            logger.error(f"[ADMIN] Migration failed {migration_name}: {e}")
            return jsonify({
                "status": "error",
                "error": str(e),
                "migration": migration_name
            }), 500
        finally:
            pool.putconn(conn)
            
    except Exception as e:
        logger.error(f"[ADMIN] Migration endpoint error: {e}")
        return make_response(jsonify({"status": "error", "error": str(e)}), 500)

@app.route("/admin/geocoding/migrate", methods=["POST"])
def run_geocoding_migration():
    """Run the geocoding schema migration (no PostGIS)."""
    try:
        # Admin auth check
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        
        migration_sql = """
-- Geocoded locations cache (persistent)
CREATE TABLE IF NOT EXISTS geocoded_locations (
    id SERIAL PRIMARY KEY,
    location_text TEXT UNIQUE NOT NULL,
    normalized_text TEXT,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    country_code VARCHAR(5),
    admin_level_1 TEXT,
    admin_level_2 TEXT,
    confidence INTEGER,
    source VARCHAR(50) DEFAULT 'opencage',
    created_at TIMESTAMPTZ DEFAULT now(),
    last_used_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_geocoded_lookup ON geocoded_locations(location_text);
CREATE INDEX IF NOT EXISTS idx_geocoded_normalized ON geocoded_locations(normalized_text);
CREATE INDEX IF NOT EXISTS idx_geocoded_latlon ON geocoded_locations(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_geocoded_country ON geocoded_locations(country_code);

-- Traveler profiles
CREATE TABLE IF NOT EXISTS traveler_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    email TEXT NOT NULL,
    name TEXT,
    current_location TEXT,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    country_code VARCHAR(5),
    alert_radius_km INTEGER DEFAULT 50,
    active BOOLEAN DEFAULT true,
    last_alert_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_traveler_latlon ON traveler_profiles(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_traveler_active ON traveler_profiles(active) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_traveler_email ON traveler_profiles(email);

-- Proximity alerts log
CREATE TABLE IF NOT EXISTS proximity_alerts (
    id SERIAL PRIMARY KEY,
    traveler_id INTEGER REFERENCES traveler_profiles(id) ON DELETE CASCADE,
    threat_id BIGINT,
    threat_source VARCHAR(50),
    threat_date DATE,
    distance_km NUMERIC(6, 2),
    severity_score NUMERIC(4, 2),
    alert_method VARCHAR(20),
    sent_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_proximity_traveler ON proximity_alerts(traveler_id);
CREATE INDEX IF NOT EXISTS idx_proximity_sent_at ON proximity_alerts(sent_at);

-- Update GDELT events
ALTER TABLE gdelt_events ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 7);
ALTER TABLE gdelt_events ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 7);
CREATE INDEX IF NOT EXISTS idx_gdelt_latlon ON gdelt_events(latitude, longitude);
"""
        
        db_url = os.getenv('DATABASE_URL')
        conn = psycopg2.connect(db_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        # Execute migration
        cur.execute(migration_sql)
        
        # Update GDELT lat/lon from existing columns (with bounds check)
        cur.execute("""
            UPDATE gdelt_events 
            SET latitude = action_lat, longitude = action_long
            WHERE latitude IS NULL 
            AND action_lat IS NOT NULL 
            AND action_lat BETWEEN -90 AND 90
            AND action_long BETWEEN -180 AND 180;
        """)
        updated_gdelt = cur.rowcount
        
        # Conditionally add columns to alerts if table exists
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alerts') THEN
                    ALTER TABLE alerts ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 7);
                    ALTER TABLE alerts ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 7);
                    ALTER TABLE alerts ADD COLUMN IF NOT EXISTS geocoded_location_id INTEGER REFERENCES geocoded_locations(id);
                    CREATE INDEX IF NOT EXISTS idx_alerts_latlon ON alerts(latitude, longitude);
                END IF;
            END $$;
        """)
        
        # Conditionally add columns to raw_alerts if table exists
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'raw_alerts') THEN
                    ALTER TABLE raw_alerts ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 7);
                    ALTER TABLE raw_alerts ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 7);
                    ALTER TABLE raw_alerts ADD COLUMN IF NOT EXISTS geocoded_location_id INTEGER REFERENCES geocoded_locations(id);
                    CREATE INDEX IF NOT EXISTS idx_raw_alerts_latlon ON raw_alerts(latitude, longitude);
                END IF;
            END $$;
        """)
        
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "Geocoding schema migration completed",
            "updated_gdelt_rows": updated_gdelt
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/db/tables", methods=["GET"])
def check_db_tables():
    """Check all database tables and row counts."""
    try:
        # Admin auth check
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        import psycopg2
        db_url = os.getenv('DATABASE_URL')
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # Get all tables
        cur.execute("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename;
        """)
        tables = {}
        for (table_name,) in cur.fetchall():
            cur.execute(f"SELECT COUNT(*) FROM {table_name};")
            count = cur.fetchone()[0]
            tables[table_name] = count
        
        # Check if alerts exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'alerts'
            );
        """)
        alerts_exists = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return jsonify({
            "tables": tables,
            "alerts_exists": alerts_exists,
            "total_tables": len(tables)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/postgis/status", methods=["GET"])
def check_postgis_status():
    """Check PostgreSQL extensions, especially PostGIS availability."""
    try:
        # Admin auth check
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        import psycopg2
        db_url = os.getenv('DATABASE_URL')
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # Check available extensions
        cur.execute("""
            SELECT name, default_version, installed_version
            FROM pg_available_extensions
            WHERE name LIKE '%postgis%' OR name LIKE '%spatial%'
            ORDER BY name;
        """)
        available = [{"name": r[0], "default_version": r[1], "installed_version": r[2]} 
                    for r in cur.fetchall()]
        
        # Check installed extensions
        cur.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname;")
        installed = [{"name": r[0], "version": r[1]} for r in cur.fetchall()]
        
        # Check PostgreSQL version
        cur.execute("SELECT version();")
        pg_version = cur.fetchone()[0]

        # Connection/server diagnostics
        cur.execute("SELECT current_database(), inet_server_addr(), inet_server_port();")
        db_name, server_ip, server_port = cur.fetchone()
        cur.execute("SELECT inet_client_addr();")
        client_ip = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return jsonify({
            "postgresql_version": pg_version,
            "postgis_available": available,
            "installed_extensions": installed,
            "postgis_installed": any(e["name"] == "postgis" for e in installed),
            "db_target": {
                "url_host": (db_url.split('@')[1].split(':')[0] if '@' in db_url else ""),
                "db_name": db_name,
                "server_ip": server_ip,
                "server_port": server_port,
                "client_ip": client_ip,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/opencage/migrate", methods=["POST"])
def run_opencage_migration():
    """Run OpenCage geocoding schema migration."""
    try:
        # Admin auth check
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
        
        db_url = os.getenv('DATABASE_URL')
        conn = psycopg2.connect(db_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        # First check what tables exist
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """)
        existing_tables = [r[0] for r in cur.fetchall()]
        
        # Read migration SQL from file
        migration_path = os.path.join(os.path.dirname(__file__), 'migrate_opencage_geocoding.sql')
        with open(migration_path, 'r') as f:
            migration_sql = f.read()
        
        # Execute migration
        cur.execute(migration_sql)
        
        # Verification
        cur.execute("SELECT PostGIS_Version();")
        pg_version = cur.fetchone()[0]
        
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('geocoded_locations', 'traveler_profiles', 'proximity_alerts', 'geocoding_quota_log')
            ORDER BY table_name;
        """)
        tables = [r[0] for r in cur.fetchall()]
        
        # Check if geom columns were added (only if tables exist)
        geom_cols = []
        for table in ['alerts', 'raw_alerts']:
            if table in existing_tables:
                cur.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = 'public' 
                    AND table_name = '{table}'
                    AND column_name = 'geom';
                """)
                if cur.fetchone():
                    geom_cols.append({"table": table, "column": "geom"})
        
        # Count alerts with coords (only if tables exist)
        alert_count = 0
        raw_count = 0
        if 'alerts' in existing_tables:
            cur.execute("SELECT COUNT(*) FROM alerts WHERE latitude IS NOT NULL AND longitude IS NOT NULL;")
            alert_count = cur.fetchone()[0]
        if 'raw_alerts' in existing_tables:
            cur.execute("SELECT COUNT(*) FROM raw_alerts WHERE latitude IS NOT NULL AND longitude IS NOT NULL;")
            raw_count = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "OpenCage migration completed successfully",
            "existing_tables": existing_tables,
            "postgis_version": pg_version,
            "tables_created": tables,
            "geom_columns_added": geom_cols,
            "alerts_with_coords": alert_count,
            "raw_alerts_with_coords": raw_count,
            "next_steps": [
                "Backfill geom columns: POST /admin/opencage/backfill",
                "Test spatial queries",
                "Deploy OpenCage geocoding service"
            ]
        })
    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "success": False
        }), 500

@app.route("/admin/acled/run", methods=["POST"])
def trigger_acled_collection():
    """Manually trigger ACLED intelligence collection (admin only).
    
    Query params:
        countries: Comma-separated list (default: from env)
        days_back: Number of days to fetch (default: 1, max: 7)
    
    Example:
        POST /admin/acled/run?countries=Nigeria,Kenya&days_back=3
        Header: X-API-Key: your_admin_key
    """
    try:
        # Admin auth check
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        # Parse optional parameters
        countries_param = request.args.get("countries")
        days_back = min(int(request.args.get("days_back", 1)), 7)  # Max 7 days
        
        countries = None
        if countries_param:
            countries = [c.strip() for c in countries_param.split(",") if c.strip()]
        
        # Run ACLED collector
        from acled_collector import run_acled_collector
        result = run_acled_collector(countries=countries, days_back=days_back)
        
        return jsonify({
            "status": "success" if result.get("success") else "error",
            "events_fetched": result.get("events_fetched", 0),
            "events_inserted": result.get("events_inserted", 0),
            "duration_seconds": result.get("duration_seconds", 0),
            "countries": countries or "default",
            "days_back": days_back,
            "error": result.get("error"),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
        
    except Exception as e:
        logger.error(f"ACLED manual trigger failed: {e}", exc_info=True)
        return make_response(jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }), 500)

# ---------- Imports: plan / advisor / engines ----------
try:
    from plan_utils import (
        ensure_user_exists,
        get_plan_limits,
        check_user_message_quota,
        increment_user_message_usage,
        require_paid_feature,
        get_plan,
        DEFAULT_PLAN,
    )
except Exception as e:
    logger.error("plan_utils import failed: %s", e)
    ensure_user_exists = get_plan_limits = check_user_message_quota = increment_user_message_usage = None
    require_paid_feature = None
    get_plan = None
    DEFAULT_PLAN = "FREE"

# ---------- Advisory orchestrator (prefer chat_handler) ----------
_advisor_callable = None
try:
    # full payload: returns { reply, alerts, plan, usage, session_id }
    from chat_handler import handle_user_query as _advisor_callable
except Exception:
    try:
        # fallback: if someone provided a matching entrypoint in advisor.py
        from advisor import handle_user_query as _advisor_callable
    except Exception:
        try:
            # last-gasp fallbacks to legacy names
            from advisor import generate_advice as _advisor_callable
        except Exception as e:
            logger.error("advisor/chat_handler import failed: %s", e)
            _advisor_callable = None

# Try to import background status helper from chat_handler (optional)
try:
    from chat_handler import get_background_status, start_background_job, handle_user_query
    logger.info("Successfully imported chat_handler background functions")
except Exception as e:
    logger.info("chat_handler background functions import failed: %s", e)
    get_background_status = None
    start_background_job = None
    handle_user_query = None

# RSS & Threat Engine
try:
    from rss_processor import ingest_all_feeds_to_db
except Exception as e:
    logger.error("rss_processor import failed: %s", e)
    ingest_all_feeds_to_db = None

try:
    from threat_engine import enrich_and_store_alerts
except Exception as e:
    logger.error("threat_engine import failed: %s", e)
    enrich_and_store_alerts = None

# Newsletter (unmetered; login required & verified)
try:
    from newsletter import subscribe_to_newsletter
except Exception as e:
    logger.error("newsletter import failed: %s", e)
    subscribe_to_newsletter = None

# Paid, unmetered feature modules (guarded by plan)
try:
    from generate_pdf import generate_pdf_advisory
except Exception as e:
    logger.error("generate_pdf import failed: %s", e)
    generate_pdf_advisory = None

try:
    from email_dispatcher import send_email
except Exception as e:
    logger.error("email_dispatcher import failed: %s", e)
    send_email = None

try:
    from push_dispatcher import send_push
except Exception as e:
    logger.error("push_dispatcher import failed: %s", e)
    send_push = None

try:
    from telegram_dispatcher import send_telegram_message
except Exception as e:
    logger.error("telegram_dispatcher import failed: %s", e)
    send_telegram_message = None

# Auth / Verification
try:
    from auth_utils import (
        register_user,
        authenticate_user,
        rotate_refresh_token,
        create_access_token,
        login_required,
        get_logged_in_email,
    )
except Exception as e:
    logger.error("auth_utils import failed: %s", e)
    register_user = authenticate_user = rotate_refresh_token = create_access_token = None
    login_required = None
    get_logged_in_email = None

try:
    from verification_utils import (
        issue_verification_code,
        verify_code as verify_email_code,
        verification_status,
    )
except Exception as e:
    logger.error("verification_utils import failed: %s", e)
    issue_verification_code = verify_email_code = verification_status = None

# DB utils for some handy reads / writes
try:
    from db_utils import fetch_all, fetch_one, execute
except Exception:
    fetch_all = None
    fetch_one = None
    execute = None

# psycopg2 Json helper for jsonb updates
try:
    from psycopg2.extras import Json
except Exception:
    Json = lambda x: x  # best-effort fallback if extras is unavailable

# Feature gating & plan feature access
try:
    from config.plans import PLAN_FEATURES, get_plan_feature, get_feature_limit, has_feature
except Exception as e:
    logger.warning("config.plans import failed: %s", e)
    PLAN_FEATURES = {}
    def get_plan_feature(plan, feature, default=None):
        return default
    def get_feature_limit(plan, feature):
        return 0
    def has_feature(plan, feature):
        return False
try:
    from utils.feature_gates import (
        requires_feature,
        check_usage_limit,
        check_feature_access,
        check_feature_limit,
    )
except Exception as e:
    logger.warning("feature_gates import failed: %s", e)
    def requires_feature(name):
        def deco(fn):
            return fn
        return deco
    def check_usage_limit(name, increment=False):
        def deco(fn):
            return fn
        return deco
    check_feature_access = requires_feature
    check_feature_limit = requires_feature

# ---------- Rate limiter setup ----------
# Use Redis for storage in multi-worker deployments: set RATE_LIMIT_STORAGE to a redis:// URL
RATE_LIMIT_STORAGE = os.getenv("RATE_LIMIT_STORAGE", None)

# Key function: prefer authenticated user identity when available, else remote IP
def _limiter_key():
    try:
        if get_logged_in_email:
            em = get_logged_in_email()
            if em:
                return f"user:{em.strip().lower()}"
    except Exception:
        pass
    try:
        if get_remote_address:
            return get_remote_address()
    except Exception:
        pass
    return "anonymous"

if Limiter is not None:
    try:
        limiter = Limiter(
            key_func=_limiter_key,
            default_limits=["200 per day", "50 per hour"],
            storage_uri=RATE_LIMIT_STORAGE,
        )
        limiter.init_app(app)
        logger.info("Flask-Limiter initialized (storage=%s)", "redis" if RATE_LIMIT_STORAGE else "in-memory")
    except Exception as e:
        logger.warning("Flask-Limiter initialization failed: %s (continuing without limiter)", e)
        limiter = None
else:
    limiter = None

# Default rates (override with env)
CHAT_RATE = os.getenv("CHAT_RATE", "10 per minute;200 per day")
SEARCH_RATE = os.getenv("SEARCH_RATE", "20 per minute;500 per hour")
BATCH_ENRICH_RATE = os.getenv("BATCH_ENRICH_RATE", "5 per minute;100 per hour")
TRAVEL_RISK_RATE = os.getenv("TRAVEL_RISK_RATE", "5 per minute;100 per hour")
CHAT_QUERY_MAX_CHARS = int(os.getenv("CHAT_QUERY_MAX_CHARS", "5000"))

# SOCMINT rates (platform-specific)

# ---------- Cache setup for travel risk ----------
try:
    import redis
    REDIS_URL = os.getenv("REDIS_URL")
    if REDIS_URL:
        travel_risk_cache = redis.from_url(REDIS_URL, decode_responses=True)
        logger.info("Travel risk cache: Redis enabled")
    else:
        travel_risk_cache = None
        logger.info("Travel risk cache: Redis not configured, using in-memory fallback")
except Exception as e:
    travel_risk_cache = None
    logger.warning(f"Travel risk cache initialization failed: {e}")

# In-memory fallback cache (TTL-based)
travel_risk_memory_cache = {}
TRAVEL_RISK_CACHE_TTL = 900  # 15 minutes
SOCMINT_INSTAGRAM_RATE = os.getenv("SOCMINT_INSTAGRAM_RATE", "30 per minute")
SOCMINT_FACEBOOK_RATE = os.getenv("SOCMINT_FACEBOOK_RATE", "10 per minute")  # Stricter due to block risk

# ---------- Conditional limiter decorator ----------
def conditional_limit(rate: str):
    """
    Decorator factory: applies limiter.limit(rate) if limiter is available.
    Ensures we don't duplicate route implementations when limiter is absent.
    """
    def deco(f: Callable):
        if limiter:
            return limiter.limit(rate)(f)
        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)
        return wrapper
    return deco

# ---------- Centralized validation helper ----------
def validate_query(query_val: Any, max_len: int = CHAT_QUERY_MAX_CHARS) -> str:
    """
    Validate and normalize query string. Raises ValueError on invalid input.
    Allows common whitespace characters (\n, \r, \t) for multi-line prompts.
    """
    if not isinstance(query_val, str):
        raise ValueError("Query must be a string")
    query = query_val.strip()
    if not query:
        raise ValueError("Query cannot be empty")
    if len(query) > int(max_len):
        raise ValueError(f"Query too long (max {max_len} chars)")
    # Allow common whitespace but reject other non-printable characters
    for ch in query:
        if ch in ("\n", "\r", "\t"):
            continue
        if not ch.isprintable():
            raise ValueError("Query contains invalid characters")
    return query

# ---------- Optional psycopg2 fallback for Telegram linking ----------
DATABASE_URL = CONFIG.database.url
_psql_ok = True
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception as e:
    _psql_ok = False
    RealDictCursor = None

def _psql_conn():
    if not DATABASE_URL or not _psql_ok:
        raise RuntimeError("psycopg2 or DATABASE_URL not available")
    return psycopg2.connect(DATABASE_URL)

def _ensure_telegram_table():
    """
    Creates the telegram_links table if not present.
    Tries db_utils.execute first; falls back to psycopg2.
    """
    sql = """
    CREATE TABLE IF NOT EXISTS telegram_links (
      user_email TEXT PRIMARY KEY,
      chat_id    TEXT NOT NULL,
      handle     TEXT,
      linked_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    try:
        if execute is not None:
            execute(sql, ())  # params tuple for helpers that require it
            return
    except Exception as e:
        logger.info("db_utils.execute failed creating telegram_links, falling back: %s", e)

    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor() as cur:
                cur.execute(sql)
                conn.commit()
        except Exception as e:
            logger.error("Failed to create telegram_links via psycopg2: %s", e)

def _ensure_email_alerts_table():
    """
    Stores a user's incident email alerts preference.
    """
    sql = """
    CREATE TABLE IF NOT EXISTS email_alerts (
      user_email TEXT PRIMARY KEY,
      enabled    BOOLEAN NOT NULL DEFAULT TRUE,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    try:
        if execute is not None:
            execute(sql, ())  # params tuple for helpers that require it
            return
    except Exception as e:
        logger.info("db_utils.execute failed creating email_alerts, falling back: %s", e)

    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor() as cur:
                cur.execute(sql)
                conn.commit()
        except Exception as e:
            logger.error("Failed to create email_alerts via psycopg2: %s", e)

# ---------- Helpers ----------
def _json_request() -> Dict[str, Any]:
    try:
        return request.get_json(force=True, silent=True) or {}
    except Exception:
        return {}

def _require_email(payload: Dict[str, Any]) -> Optional[str]:
    # Legacy fallback for unguarded routes; JWT-guarded routes use get_logged_in_email()
    email = request.headers.get("X-User-Email") or payload.get("email")
    return email.strip().lower() if isinstance(email, str) and email.strip() else None

def _advisor_call(query: str, email: str, profile_data: Optional[Dict[str, Any]], input_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if _advisor_callable is None:
        raise RuntimeError("Advisor module is not available")
    # Try payload style first (advisor shim / chat_handler both accept this),
    # then fall back to legacy signatures.
    try:
        return _advisor_callable({"query": query, "profile_data": profile_data, "input_data": input_data}, email=email)
    except TypeError:
        try:
            return _advisor_callable(query, email=email, profile_data=profile_data)
        except TypeError:
            return _advisor_callable(query)

def _is_verified(email: str) -> bool:
    if not fetch_one:
        return False
    try:
        row = fetch_one("SELECT email_verified FROM users WHERE email=%s", (email,))
        return bool(row and row[0])
    except Exception:
        return False

def _load_user_profile(email: str) -> Dict[str, Any]:
    """Return merged profile data from users + optional user_profiles.profile_json."""
    if not fetch_one:
        return {}
    row = fetch_one(
        "SELECT email, plan, name, employer, email_verified, "
        "preferred_region, preferred_threat_type, home_location, extra_details "
        "FROM users WHERE email=%s",
        (email,),
    )
    if not row:
        return {}

    data: Dict[str, Any] = {
        "email": row[0],
        "plan": row[1],
        "name": row[2],
        "employer": row[3],
        "email_verified": bool(row[4]),
        "preferred_region": row[5],
        "preferred_threat_type": row[6],
        "home_location": row[7],
        "extra_details": row[8] or {},
    }

    # Optional extended profile
    try:
        pr = fetch_one("SELECT profile_json FROM user_profiles WHERE email=%s", (email,))
        if pr and pr[0]:
            data["profile"] = pr[0]
    except Exception:
        pass

    # --- Attach usage and all feature limits ---
    chat_used = 0
    all_limits = {}
    try:
        from plan_utils import get_usage, get_plan_limits
        u = get_usage(email) if get_usage else None
        if isinstance(u, dict):
            chat_used = int(u.get("chat_messages_used", 0))

        # Get full plan limits
        all_limits = get_plan_limits(email) or {}
    except Exception as e:
        logger.info("usage resolution failed in _load_user_profile: %s", e)
        all_limits = {"chat_messages_per_month": 3, "alerts_days": 7, "alerts_max_results": 30}

    # Nested usage structure
    data.setdefault("usage", {})
    data["usage"]["chat_messages_used"] = chat_used
    data["usage"]["chat_messages_limit"] = all_limits.get("chat_messages_per_month", 3)

    # Backward-compat top-level fields
    data["used"] = chat_used
    data["limit"] = all_limits.get("chat_messages_per_month", 3)

    # Feature access limits
    data["limits"] = {
        "alerts_days": all_limits.get("alerts_days", 7),
        "alerts_max_results": all_limits.get("alerts_max_results", 30),
        "map_days": all_limits.get("map_days", 7),
        "timeline_days": all_limits.get("timeline_days", 7),
        "statistics_days": all_limits.get("statistics_days", 7),
            "monitoring_days": all_limits.get("monitoring_days", 7),
            # Added for consistency with /auth/status limits block
            "chat_messages_per_month": all_limits.get("chat_messages_per_month", 3),
    }

    return data

# ---------- Routes ----------
@app.route("/healthz", methods=["GET"])
def healthz():
    data = {
        "ok": True,
        "version": "2025-08-13",
        "advisor": _advisor_callable is not None,
        "rss": ingest_all_feeds_to_db is not None,
        "engine": enrich_and_store_alerts is not None,
        "plan_utils": ensure_user_exists is not None,
        "newsletter": subscribe_to_newsletter is not None,
        "pdf": generate_pdf_advisory is not None,
        "email": send_email is not None,
        "push": send_push is not None,
        "telegram": send_telegram_message is not None,
        "auth": register_user is not None and authenticate_user is not None,
        "verify": issue_verification_code is not None and verify_email_code is not None,
    }
    return jsonify(data)

# ---------- Auth & Verification (unmetered) ----------
@app.route("/auth/register", methods=["POST", "OPTIONS"])
def auth_register():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    if register_user is None:
        return _build_cors_response(make_response(jsonify({"error": "Auth unavailable"}), 503))

    payload = _json_request()
    email = (payload.get("email") or "").strip().lower()
    password = (payload.get("password") or "").strip()
    name = (payload.get("name") or "").strip() or None
    employer = (payload.get("employer") or "").strip() or None
    plan = (payload.get("plan") or os.getenv("DEFAULT_PLAN", "FREE")).strip().upper()

    if not email or not password:
        return _build_cors_response(make_response(jsonify({"error": "Missing email or password"}), 400))

    ok, msg = register_user(email=email, password=password, name=name, employer=employer, plan=plan)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 400))

    # Optionally issue a verification code right away
    sent = False
    if issue_verification_code:
        client_ip = request.headers.get("CF-Connecting-IP") or request.remote_addr
        sent, _ = issue_verification_code(email, ip_address=client_ip)

    return _build_cors_response(jsonify({"ok": True, "verification_sent": bool(sent)}))

@app.route("/auth/login", methods=["POST", "OPTIONS"])
def auth_login():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    if authenticate_user is None:
        return _build_cors_response(make_response(jsonify({"error": "Auth unavailable"}), 503))

    payload = _json_request()
    email = (payload.get("email") or "").strip().lower()
    password = (payload.get("password") or "").strip()
    if not email or not password:
        return _build_cors_response(make_response(jsonify({"error": "Missing email or password"}), 400))

    ok, msg, access_token, refresh_bundle = authenticate_user(email, password)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 401))

    verified = False
    if verification_status:
        try:
            verified, _ = verification_status(email)
        except Exception:
            verified = _is_verified(email)

    # Get plan name from database
    plan_name = DEFAULT_PLAN
    if get_plan:
        try:
            p = get_plan(email)
            if isinstance(p, str) and p:
                plan_name = p.upper()
        except Exception:
            pass

    # Get usage data
    usage_data = {"chat_messages_used": 0, "chat_messages_limit": 3}
    try:
        from plan_utils import get_usage, get_plan_limits
        u = get_usage(email)
        if isinstance(u, dict):
            usage_data["chat_messages_used"] = u.get("chat_messages_used", 0)
        
        # Determine limit based on plan
        if plan_name == "PRO":
            usage_data["chat_messages_limit"] = 1000
        elif plan_name in ("VIP", "ENTERPRISE"):
            usage_data["chat_messages_limit"] = 5000
        else:
            try:
                limits = get_plan_limits(email) or {}
                usage_data["chat_messages_limit"] = limits.get("chat_messages_per_month", 3)
            except Exception:
                usage_data["chat_messages_limit"] = 3
    except Exception as e:
        logger.warning("Failed to get usage in auth_login: %s", e)

    return _build_cors_response(jsonify({
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_bundle,
        "email_verified": bool(verified),
        "plan": plan_name,
        "quota": {
            "used": usage_data["chat_messages_used"],
            "limit": usage_data["chat_messages_limit"],
            "plan": plan_name
        }
    }))

@app.route("/auth/refresh", methods=["POST", "OPTIONS"])
def auth_refresh():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    if rotate_refresh_token is None or create_access_token is None:
        return _build_cors_response(make_response(jsonify({"error": "Auth unavailable"}), 503))

    payload = _json_request()
    email = (payload.get("email") or "").strip().lower()
    bundle = (payload.get("refresh_bundle") or "").strip()
    if not email or ":" not in bundle:
        return _build_cors_response(make_response(jsonify({"error": "Missing email or refresh_bundle"}), 400))

    rid, token = bundle.split(":", 1)
    ok, new_token, new_rid = rotate_refresh_token(rid, token)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": "Invalid or expired refresh token"}), 401))

    plan_name = "FREE"
    if get_plan:
        try:
            p = get_plan(email)
            if isinstance(p, str) and p:
                plan_name = p.upper()
        except Exception:
            pass

    try:
        access = create_access_token(email, plan_name)
    except Exception as e:
        logger.error("create_access_token failed: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Failed to issue access token"}), 500))

    return _build_cors_response(jsonify({
        "ok": True,
        "access_token": access,
        "refresh_bundle": f"{new_rid}:{new_token}",
    }))

@app.route("/auth/verify/send", methods=["POST", "OPTIONS"])
def auth_verify_send():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    if issue_verification_code is None:
        return _build_cors_response(make_response(jsonify({"error": "Verification unavailable"}), 503))

    payload = _json_request()
    email = (payload.get("email") or "").strip().lower()
    if not email:
        return _build_cors_response(make_response(jsonify({"error": "Missing email"}), 400))

    client_ip = request.headers.get("CF-Connecting-IP") or request.remote_addr
    ok, msg = issue_verification_code(email, ip_address=client_ip)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 429))
    return _build_cors_response(jsonify({"ok": True, "message": msg}))

@app.route("/auth/verify/confirm", methods=["POST", "OPTIONS"])
def auth_verify_confirm():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    if verify_email_code is None:
        return _build_cors_response(make_response(jsonify({"error": "Verification unavailable"}), 503))

    payload = _json_request()
    email = (payload.get("email") or "").strip().lower()
    code = (payload.get("code") or "").strip()
    if not email or not code:
        return _build_cors_response(make_response(jsonify({"error": "Missing email or code"}), 400))

    ok, msg = verify_email_code(email, code)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 400))
    return _build_cors_response(jsonify({"ok": True, "message": msg}))

# ---------- Profile (login required; unmetered) ----------
@app.route("/profile/me", methods=["GET"])
@login_required
def profile_me():
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))
    email = get_logged_in_email()
    user = _load_user_profile(email)
    return _build_cors_response(jsonify({"ok": True, "user": user}))

@app.route("/profile/update", methods=["POST", "OPTIONS"])
def profile_update_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _profile_update_impl()

@app.route("/profile/update", methods=["POST"])
@login_required
def _profile_update_impl():
    if execute is None or fetch_one is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))

    email = get_logged_in_email()
    payload = _json_request()

    # Only update fields that were provided
    updatable = ("name", "employer", "preferred_region", "preferred_threat_type", "home_location")
    fields = {k: (payload.get(k) or "").strip() for k in updatable if k in payload}
    extra_details = payload.get("extra_details")  # dict (optional)
    profile_json = payload.get("profile")         # dict (optional; stored in user_profiles if present)

    # Build dynamic UPDATE for users
    if fields or (extra_details is not None):
        sets = []
        params = []
        for k, v in fields.items():
            sets.append(f"{k}=%s")
            params.append(v)
        if extra_details is not None:
            sets.append("extra_details=%s")
            try:
                params.append(Json(extra_details))
            except Exception:
                params.append(extra_details)
        sets_sql = ", ".join(sets)
        try:
            execute(f"UPDATE users SET {sets_sql} WHERE email=%s", tuple(params + [email]))
        except Exception as e:
            logger.error("profile update failed: %s", e)
            return _build_cors_response(make_response(jsonify({"error": "Profile update failed"}), 500))

    # Optional: upsert into user_profiles if provided
    if profile_json is not None:
        try:
            execute(
                "INSERT INTO user_profiles (email, profile_json) "
                "VALUES (%s, %s) "
                "ON CONFLICT (email) DO UPDATE SET profile_json = EXCLUDED.profile_json",
                (email, Json(profile_json)),
            )
        except Exception as e:
            # Non-fatal if table/column doesn't exist
            logger.info("user_profiles upsert skipped: %s", e)

    user = _load_user_profile(email)
    return _build_cors_response(jsonify({"ok": True, "user": user}))

# ---------- Chat (metered AFTER success; VERIFIED required) ----------
# Frontend-expected route (alias for /chat)
@app.route("/api/sentinel-chat", methods=["POST", "OPTIONS"])
@login_required
@conditional_limit(CHAT_RATE)  # limiter applied only if initialized
def api_sentinel_chat():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _chat_impl()

@app.route("/chat", methods=["POST", "OPTIONS"])
@login_required
@conditional_limit(CHAT_RATE)  # limiter applied only if initialized
def chat_options():
    # keep preflight separate to preserve decorator behavior below
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _chat_impl()


# Single chat implementation using async-first approach for better reliability
def _chat_impl():
    logger.info("=== CHAT ENDPOINT START ===")
    logger.info("Request method: %s", request.method)
    logger.info("Request headers: %s", dict(request.headers))
    logger.info("Request content type: %s", request.content_type)
    
    try:
        logger.info("Starting async-first chat implementation")
        
        # Check if user is authenticated via g object
        user_email = getattr(g, 'user_email', None)
        user_plan = getattr(g, 'user_plan', None)
        logger.info("Authenticated user: email=%s, plan=%s", user_email, user_plan)
        
        payload = _json_request()
        logger.info("Payload received: %s", {k: str(v)[:100] for k, v in payload.items()})
    except Exception as e:
        logger.error("Failed to parse JSON request: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Invalid JSON request"}), 400))
    
    # --- Validation ---
    try:
        query = validate_query(payload.get("query"))
        logger.info("Query validation successful: %s", query[:100])
    except ValueError as ve:
        logger.error("Query validation failed: %s", ve)
        return _build_cors_response(make_response(jsonify({"error": str(ve)}), 400))
    
    try:
        email = get_logged_in_email()
        logger.info("User email obtained: %s", email)
    except Exception as e:
        logger.error("Failed to get user email: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Authentication required"}), 401))
    
    profile_data = payload.get("profile_data") or {}
    input_data = payload.get("input_data") or {}
    logger.info("Profile and input data extracted successfully")
    
    # ----- Enforce VERIFIED email for chat -----
    verified = False
    if verification_status:
        try:
            verified, _ = verification_status(email)
        except Exception:
            verified = _is_verified(email)
    else:
        verified = _is_verified(email)

    if not verified:
        return _build_cors_response(make_response(jsonify({
            "error": "Email not verified. Please verify your email to use chat.",
            "action": {
                "send_code": "/auth/verify/send",
                "confirm_code": "/auth/verify/confirm"
            }
        }), 403))

    # ----- Plan usage (chat-only) -----
    try:
        if ensure_user_exists:
            ensure_user_exists(email, plan=os.getenv("DEFAULT_PLAN", "FREE"))
        if get_plan_limits and check_user_message_quota:
            plan_limits = get_plan_limits(email)
            ok, msg = check_user_message_quota(email, plan_limits)
            if not ok:
                # Build quota block for frontend contract
                plan_name = (get_plan(email) if get_plan else os.getenv("DEFAULT_PLAN", "FREE")).strip().upper()
                used_val = 0
                limit_val = 3
                try:
                    from plan_utils import get_usage
                    u = get_usage(email)
                    if isinstance(u, dict):
                        used_val = int(u.get("chat_messages_used", 0))
                except Exception:
                    pass
                if plan_name == "PRO":
                    limit_val = 1000
                elif plan_name in ("VIP", "ENTERPRISE"):
                    limit_val = 5000
                else:
                    try:
                        limit_val = int(plan_limits.get("chat_messages_per_month", 3))
                    except Exception:
                        limit_val = 3

                return _build_cors_response(make_response(jsonify({
                    "code": "QUOTA_EXCEEDED",
                    "error": "Monthly chat quota reached.",
                    "quota": {"used": used_val, "limit": limit_val, "plan": plan_name}
                }), 403))
    except Exception as e:
        logger.error("plan check failed: %s", e)
        pass
    
    # --- Always spawn background job ---
    session_id = str(__import__('uuid').uuid4())
    logger.info("Generated session ID: %s", session_id)
    
    # Check if background processing is available
    if not start_background_job or not handle_user_query:
        logger.error("Background processing unavailable - functions not imported")
        logger.error("start_background_job available: %s", start_background_job is not None)
        logger.error("handle_user_query available: %s", handle_user_query is not None)
        return _build_cors_response(make_response(jsonify({"error": "Background processing unavailable"}), 503))
    
    # Prepare arguments for background processing
    try:
        logger.info("Starting background job for session: %s", session_id)
        
        # Call background job with proper arguments for handle_user_query
        start_background_job(
            session_id,
            handle_user_query,
            query,  # message parameter
            email,  # email parameter
            body={"profile_data": profile_data, "input_data": input_data}  # body parameter
        )
        
        logger.info("Background job started successfully for session: %s", session_id)
        
        # Increment usage immediately (since we're accepting the request)
        try:
            if increment_user_message_usage:
                increment_user_message_usage(email)
                logger.info("Usage incremented for user: %s", email)
        except Exception as e:
            logger.warning("Usage increment failed: %s", e)
        
        # Resolve current quota after accepting request (usage has been incremented)
        try:
            from plan_utils import get_usage, get_plan_limits
            plan_name = (get_plan(email) if get_plan else os.getenv("DEFAULT_PLAN", "FREE")).strip().upper()
            used_val = 0
            lim_val = 3
            u = get_usage(email) if get_usage else None
            if isinstance(u, dict):
                used_val = int(u.get("chat_messages_used", 0))
            if plan_name == "PRO":
                lim_val = 1000
            elif plan_name in ("VIP", "ENTERPRISE"):
                lim_val = 5000
            else:
                try:
                    limits = get_plan_limits(email) or {}
                    lim_val = int(limits.get("chat_messages_per_month", 3))
                except Exception:
                    lim_val = 3
        except Exception:
            plan_name, used_val, lim_val = (os.getenv("DEFAULT_PLAN", "FREE").strip().upper(), 0, 3)

        success_response = {
            "accepted": True,
            "session_id": session_id,
            "message": "Processing your request. Poll /api/chat/status/<session_id> for results.",
            "plan": plan_name,
            "quota": {"used": used_val, "limit": lim_val, "plan": plan_name}
        }
        
        logger.info("Returning 202 response for session: %s", session_id)
        return _build_cors_response(make_response(jsonify(success_response), 202))
        
    except Exception as e:
        logger.error("Failed to start background job: %s", e)
        import traceback
        logger.error("Traceback: %s", traceback.format_exc())
        return _build_cors_response(make_response(jsonify({"error": "Failed to start processing"}), 500))

# ---------- Chat Background Status Polling Endpoint ----------
@app.route("/api/chat/status/<session_id>", methods=["GET", "OPTIONS"])
def chat_status_options(session_id):
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    # fallback to GET behavior
    return chat_status(session_id)

@app.route("/api/chat/status/<session_id>", methods=["GET"])
@login_required
def chat_status(session_id):
    """
    Poll background job status (started by chat_handler.start_background_job)
    Returns:
      - 200 with result once available,
      - 202 while pending/running,
      - 500 on failure,
      - 404 if job not found.
    """
    if get_background_status is None:
        return _build_cors_response(make_response(jsonify({"error": "Background status unavailable"}), 503))

    status = get_background_status(session_id)

    # If result is present, return it directly (200)
    if status and status.get("result"):
        return _build_cors_response(jsonify(status["result"]))

    job = status.get("job", {}) if status else {}
    if job.get("status") == "done":
        # completed but no stored result — treat as internal error
        return _build_cors_response(make_response(jsonify({"error": "Job completed but result missing"}), 500))
    elif job.get("status") == "failed":
        return _build_cors_response(make_response(jsonify({"error": job.get("error", "Job failed")}), 500))
    elif job.get("status") in ("running", "pending"):
        return _build_cors_response(make_response(jsonify({
            "status": job["status"],
            "message": "Still processing...",
            "started_at": job.get("started_at")
        }), 202))
    else:
        return _build_cors_response(make_response(jsonify({"error": "Job not found"}), 404))

# ---------- Debug quota (login required) ----------
@app.route("/api/debug-quota", methods=["GET"])
@login_required
def debug_quota():
    """Return raw and mapped quota views for debugging frontend integration."""
    # Build auth_status-like payload
    email = get_logged_in_email()
    plan_name = None
    try:
        plan_name = (get_plan(email) if get_plan else os.getenv("DEFAULT_PLAN", "FREE")).strip().upper()
    except Exception:
        plan_name = (os.getenv("DEFAULT_PLAN", "FREE")).strip().upper()

    # Resolve usage + limits
    used_val = 0
    limit_val = 3
    try:
        from plan_utils import get_usage, get_plan_limits
        u = get_usage(email) if get_usage else None
        if isinstance(u, dict):
            used_val = int(u.get("chat_messages_used", 0))
        if plan_name == "PRO":
            limit_val = 1000
        elif plan_name in ("VIP", "ENTERPRISE"):
            limit_val = 5000
        else:
            try:
                limits = get_plan_limits(email) or {}
                limit_val = int(limits.get("chat_messages_per_month", 3))
            except Exception:
                limit_val = 3
    except Exception:
        pass

    backend_auth_status = {
        "email": email,
        "plan": plan_name,
        "email_verified": _is_verified(email),
        "usage": {"chat_messages_used": used_val, "chat_messages_limit": limit_val},
    }

    # profile/me equivalent
    user_profile = _load_user_profile(email)

    mapped_from_auth_status = {
        "plan": backend_auth_status.get("plan"),
        "used": backend_auth_status.get("usage", {}).get("chat_messages_used", 0),
        "limit": backend_auth_status.get("usage", {}).get("chat_messages_limit", 0),
    }
    mapped_from_profile_me = {
        "plan": (user_profile.get("plan") or "").upper(),
        "used": user_profile.get("usage", {}).get("chat_messages_used", user_profile.get("used", 0)),
        "limit": user_profile.get("usage", {}).get("chat_messages_limit", user_profile.get("limit", 0)),
    }

    return _build_cors_response(jsonify({
        "backend": {
            "auth_status": backend_auth_status,
            "profile_me": {"ok": True, "user": user_profile}
        },
        "mapped": {
            "from_auth_status": mapped_from_auth_status,
            "from_profile_me": mapped_from_profile_me
        }
    }))

# ---------- Newsletter (unmetered; verified login required) ----------
@app.route("/newsletter/subscribe", methods=["POST", "OPTIONS"])
def newsletter_subscribe_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _newsletter_subscribe_impl()

@app.route("/newsletter/subscribe", methods=["POST"])
@login_required
def _newsletter_subscribe_impl():
    if subscribe_to_newsletter is None:
        return _build_cors_response(make_response(jsonify({"error": "Newsletter unavailable"}), 503))

    email = get_logged_in_email()
    # Require verified email
    verified = False
    if verification_status:
        try:
            verified, _ = verification_status(email)
        except Exception:
            verified = _is_verified(email)
    else:
        verified = _is_verified(email)

    if not verified:
        return _build_cors_response(make_response(jsonify({"error": "Email not verified"}), 403))

    ok = subscribe_to_newsletter(email)
    return _build_cors_response(jsonify({"ok": bool(ok)}))

# ---------- Paid, unmetered utilities ----------
@app.route("/pdf/generate", methods=["POST", "OPTIONS"])
def pdf_generate_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _pdf_generate_impl()

@app.route("/pdf/generate", methods=["POST"])
@login_required
def _pdf_generate_impl():
    if generate_pdf_advisory is None or require_paid_feature is None:
        return _build_cors_response(make_response(jsonify({"error": "PDF export unavailable"}), 503))

    email = get_logged_in_email()
    ok, msg = require_paid_feature(email)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 403))

    payload = _json_request()
    title = (payload.get("title") or "").strip() or "Sentinel Advisory"
    body_text = (payload.get("body_text") or "").strip()
    if not body_text:
        return _build_cors_response(make_response(jsonify({"error": "Missing body_text"}), 400))

    path = generate_pdf_advisory(email, title, body_text)
    if not path:
        return _build_cors_response(make_response(jsonify({"error": "PDF generation failed"}), 500))
    return _build_cors_response(jsonify({"ok": True, "path": path}))

@app.route("/email/send", methods=["POST", "OPTIONS"])
def email_send_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _email_send_impl()

@app.route("/email/send", methods=["POST"])
@login_required
def _email_send_impl():
    if send_email is None or require_paid_feature is None:
        return _build_cors_response(make_response(jsonify({"error": "Email dispatcher unavailable"}), 503))

    email = get_logged_in_email()
    ok, msg = require_paid_feature(email)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 403))

    payload = _json_request()
    to_addr = (payload.get("to") or "").strip().lower()
    subject = (payload.get("subject") or "").strip()
    html = (payload.get("html") or "").strip()
    from_addr = (payload.get("from") or None)
    if not to_addr or not subject or not html:
        return _build_cors_response(make_response(jsonify({"error": "Missing to/subject/html"}), 400))

    sent = send_email(user_email=email, to_addr=to_addr, subject=subject, html_body=html, from_addr=from_addr)
    if not sent:
        return _build_cors_response(make_response(jsonify({"error": "Email send failed"}), 500))
    return _build_cors_response(jsonify({"ok": True}))

@app.route("/push/send", methods=["POST", "OPTIONS"])
def push_send_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _push_send_impl()

@app.route("/push/send", methods=["POST"])
@login_required
def _push_send_impl():
    if send_push is None or require_paid_feature is None:
        return _build_cors_response(make_response(jsonify({"error": "Push dispatcher unavailable"}), 503))

    email = get_logged_in_email()
    ok, msg = require_paid_feature(email)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 403))

    payload = _json_request()
    device_token = (payload.get("device_token") or "").strip()
    push_payload = payload.get("payload") or {}
    if not device_token or not isinstance(push_payload, dict):
        return _build_cors_response(make_response(jsonify({"error": "Missing device_token or payload"}), 400))

    sent = send_push(user_email=email, device_token=device_token, payload=push_payload)
    if not sent:
        return _build_cors_response(make_response(jsonify({"error": "Push send failed"}), 500))
    return _build_cors_response(jsonify({"ok": True}))

@app.route("/telegram/send", methods=["POST", "OPTIONS"])
def telegram_send_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _telegram_send_impl()

@app.route("/telegram/send", methods=["POST"])
@login_required
def _telegram_send_impl():
    if send_telegram_message is None or require_paid_feature is None:
        return _build_cors_response(make_response(jsonify({"error": "Telegram send unavailable"}), 503))

    email = get_logged_in_email()
    ok, msg = require_paid_feature(email)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 403))

    payload = _json_request()
    chat_id = (payload.get("chat_id") or "").strip()
    text = (payload.get("text") or "").strip()
    parse_mode = (payload.get("parse_mode") or None)
    if not chat_id or not text:
        return _build_cors_response(make_response(jsonify({"error": "Missing chat_id or text"}), 400))

    sent = send_telegram_message(user_email=email, chat_id=chat_id, text=text, parse_mode=parse_mode)
    if not sent:
        return _build_cors_response(make_response(jsonify({"error": "Telegram send failed"}), 500))
    return _build_cors_response(jsonify({"ok": True}))

# ---------- Telegram pairing/status (paid gating happens when sending) ----------
@app.route("/telegram_status", methods=["GET", "OPTIONS"])
def telegram_status_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _telegram_status_impl()

@app.route("/telegram_status", methods=["GET"])
@login_required
def _telegram_status_impl():
    # Table ensure (safe if exists)
    _ensure_telegram_table()

    email = get_logged_in_email()

    # Try db_utils first
    if fetch_one is not None:
        try:
            row = fetch_one("SELECT chat_id, handle FROM telegram_links WHERE user_email=%s LIMIT 1", (email,))
            if row:
                # row may be tuple or dict depending on db_utils; handle both
                chat_id = row[0] if isinstance(row, tuple) else row.get("chat_id")
                handle = row[1] if isinstance(row, tuple) else row.get("handle")
                payload = {"linked": True}
                if handle:
                    payload["handle"] = handle
                return _build_cors_response(jsonify(payload))
            return _build_cors_response(jsonify({"linked": False}))
        except Exception as e:
            logger.info("telegram_status via db_utils failed, falling back: %s", e)

    # Fallback psycopg2
    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT chat_id, handle FROM telegram_links WHERE user_email=%s LIMIT 1", (email,))
                row = cur.fetchone()
            payload = {"linked": bool(row)}
            if row and row.get("handle"):
                payload["handle"] = row["handle"]
            return _build_cors_response(jsonify(payload))
        except Exception as e:
            logger.exception("telegram_status psycopg2 failed: %s", e)

    # Soft-fail
    return _build_cors_response(jsonify({"linked": False}))

@app.route("/telegram_unlink", methods=["POST", "OPTIONS"])
def telegram_unlink_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _telegram_unlink_impl()

@app.route("/telegram_unlink", methods=["POST"])
@login_required
def _telegram_unlink_impl():
    _ensure_telegram_table()
    email = get_logged_in_email()

    # Try db_utils first
    if execute is not None:
        try:
            execute("DELETE FROM telegram_links WHERE user_email=%s", (email,))
            return _build_cors_response(jsonify({"ok": True}))
        except Exception as e:
            logger.info("telegram_unlink via db_utils failed, falling back: %s", e)

    # Fallback psycopg2
    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM telegram_links WHERE user_email=%s", (email,))
                conn.commit()
            return _build_cors_response(jsonify({"ok": True}))
        except Exception as e:
            logger.exception("telegram_unlink psycopg2 failed: %s", e)
            return _build_cors_response(make_response(jsonify({"error": "unlink failed"}), 500))

    # If neither path worked:
    return _build_cors_response(make_response(jsonify({"error": "unlink unavailable"}), 503))

@app.route("/telegram_opt_in", methods=["GET", "OPTIONS"])
def telegram_opt_in_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _telegram_opt_in_impl()

@app.route("/telegram_opt_in", methods=["GET"])
@login_required
def _telegram_opt_in_impl():
    username = (os.getenv("TELEGRAM_BOT_USERNAME") or "").lstrip("@")
    if not username:
        return _build_cors_response(make_response(jsonify({"error": "Bot not configured"}), 503))

    email = get_logged_in_email()
    token = base64.urlsafe_b64encode(email.encode()).decode().rstrip("=")
    url = f"https://t.me/{username}?start={token}"

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Connect Telegram</title>
<meta http-equiv="refresh" content="0;url={url}">
</head><body>
<p>Opening Telegram… If nothing happens, tap <a href="{url}">@{username}</a>.</p>
</body></html>"""

    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return _build_cors_response(resp)

# ---------- PLAN & FEATURES for frontend ----------
@app.route("/user_plan", methods=["GET"])
@login_required
def user_plan():
    email = get_logged_in_email()

    # Plan
    plan_name = "FREE"
    if get_plan:
        try:
            p = get_plan(email)
            if isinstance(p, str) and p:
                plan_name = p.upper()
        except Exception:
            pass

    paid = plan_name in ("PRO", "ENTERPRISE")

    # Features expected by frontend
    features = {
        "alerts": paid,      # umbrella for Push + incident Email + Telegram
        "telegram": paid,
        "pdf": paid,
        "newsletter": True,  # newsletter is unmetered but requires verified login elsewhere
    }

    # Limits (normalized for UI and consistent with /auth/status)
    limits = {}
    if plan_name == "PRO":
        limits["chat_messages_limit"] = 1000
        limits["max_alert_channels"] = 10
    elif plan_name in ("VIP", "ENTERPRISE"):
        limits["chat_messages_limit"] = 5000
        limits["max_alert_channels"] = 25
    else:
        # fallback for Free or unknown plans
        limits["chat_messages_limit"] = 3
        limits["max_alert_channels"] = 1

    # Get current usage
    usage_data = {"chat_messages_used": 0}
    try:
        from plan_utils import get_usage
        u = get_usage(email)
        if isinstance(u, dict):
            usage_data["chat_messages_used"] = u.get("chat_messages_used", 0)
    except Exception as e:
        logger.warning("Failed to get usage in user_plan: %s", e)

    return _build_cors_response(jsonify({
        "plan": plan_name,
        "features": features,
        "limits": limits,
        "used": usage_data["chat_messages_used"],
        "limit": limits["chat_messages_limit"]
    }))

# ---------- Incident Email Alerts (preference, paid-gated when enabling) ----------
@app.route("/email_alerts_status", methods=["GET", "OPTIONS"])
def email_alerts_status_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _email_alerts_status_impl()

@app.route("/email_alerts_status", methods=["GET"])
@login_required
def _email_alerts_status_impl():
    _ensure_email_alerts_table()
    email = get_logged_in_email()

    enabled = False

    if fetch_one is not None:
        try:
            row = fetch_one("SELECT enabled FROM email_alerts WHERE user_email=%s LIMIT 1", (email,))
            if row is not None:
                enabled = bool(row[0] if isinstance(row, tuple) else row.get("enabled"))
            return _build_cors_response(jsonify({"enabled": enabled}))
        except Exception as e:
            logger.info("email_alerts_status via db_utils failed, falling back: %s", e)

    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT enabled FROM email_alerts WHERE user_email=%s LIMIT 1", (email,))
                r = cur.fetchone()
                if r is not None:
                    enabled = bool(r.get("enabled"))
            return _build_cors_response(jsonify({"enabled": enabled}))
        except Exception as e:
            logger.exception("email_alerts_status psycopg2 failed: %s", e)

    return _build_cors_response(jsonify({"enabled": False}))

@app.route("/email_alerts_enable", methods=["POST", "OPTIONS"])
def email_alerts_enable_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _email_alerts_enable_impl()

@app.route("/email_alerts_enable", methods=["POST"])
@login_required
def _email_alerts_enable_impl():
    _ensure_email_alerts_table()
    if require_paid_feature is None:
        return _build_cors_response(make_response(jsonify({"error": "Plan gate unavailable"}), 503))

    email = get_logged_in_email()
    ok, msg = require_paid_feature(email)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 403))

    # Upsert true
    try:
        if execute is not None:
            execute(
                "INSERT INTO email_alerts (user_email, enabled) VALUES (%s, TRUE) "
                "ON CONFLICT (user_email) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=now()",
                (email,),
            )
            return _build_cors_response(jsonify({"ok": True}))
    except Exception as e:
        logger.info("email_alerts_enable via db_utils failed, falling back: %s", e)

    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO email_alerts (user_email, enabled) VALUES (%s, TRUE) "
                    "ON CONFLICT (user_email) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=now()",
                    (email,),
                )
                conn.commit()
            return _build_cors_response(jsonify({"ok": True}))
        except Exception as e:
            logger.exception("email_alerts_enable psycopg2 failed: %s", e)
            return _build_cors_response(make_response(jsonify({"error": "enable failed"}), 500))

    return _build_cors_response(make_response(jsonify({"error": "enable unavailable"}), 503))

@app.route("/email_alerts_disable", methods=["POST", "OPTIONS"])
def email_alerts_disable_options():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _email_alerts_disable_impl()

@app.route("/email_alerts_disable", methods=["POST"])
@login_required
def _email_alerts_disable_impl():
    _ensure_email_alerts_table()
    email = get_logged_in_email()

    try:
        if execute is not None:
            execute(
                "INSERT INTO email_alerts (user_email, enabled) VALUES (%s, FALSE) "
                "ON CONFLICT (user_email) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=now()",
                (email,),
            )
            return _build_cors_response(jsonify({"ok": True}))
    except Exception as e:
        logger.info("email_alerts_disable via db_utils failed, falling back: %s", e)

    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO email_alerts (user_email, enabled) VALUES (%s, FALSE) "
                    "ON CONFLICT (user_email) DO UPDATE SET enabled=EXCLUDED.enabled, updated_at=now()",
                    (email,),
                )
                conn.commit()
            return _build_cors_response(jsonify({"ok": True}))
        except Exception as e:
            logger.exception("email_alerts_disable psycopg2 failed: %s", e)
            return _build_cors_response(make_response(jsonify({"error": "disable failed"}), 500))

    return _build_cors_response(make_response(jsonify({"error": "disable unavailable"}), 503))

# ---------- Alerts (paid-gated list for frontend) ----------
@app.route("/alerts", methods=["GET"])
@login_required
def alerts_list():
    email = get_logged_in_email()
    if require_paid_feature is None:
        return _build_cors_response(make_response(jsonify({"error": "Plan gate unavailable"}), 503))
    ok, msg = require_paid_feature(email)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 403))

    limit = int(request.args.get("limit", 100))

    sql = """
        SELECT
          uuid, title, summary, gpt_summary, link, source,
          published, region, country, city,
          category, subcategory,
          threat_level, score, confidence,
          reasoning, forecast,
          tags, early_warning_indicators,
          threat_score_components,
          source_kind, source_tag,
          latitude, longitude
        FROM alerts
        ORDER BY published DESC NULLS LAST
        LIMIT %s
    """

    # Try db_utils first
    if fetch_all is not None:
        try:
            rows = fetch_all(sql, (limit,))
            return _build_cors_response(jsonify({"alerts": rows}))
        except Exception as e:
            logger.info("/alerts via db_utils failed, falling back: %s", e)

    # Fallback psycopg2
    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
            return _build_cors_response(jsonify({"alerts": rows}))
        except Exception as e:
            logger.exception("/alerts psycopg2 failed: %s", e)
            return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

    return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))

# ---------- RSS & Engine (unmetered) ----------
@app.route("/rss/run", methods=["POST", "OPTIONS"])
def rss_run():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))

    if ingest_all_feeds_to_db is None:
        return _build_cors_response(make_response(jsonify({"error": "RSS processor unavailable"}), 503))

    payload = _json_request()
    groups = payload.get("groups") or None
    limit = int(payload.get("limit") or os.getenv("RSS_BATCH_LIMIT", 400))
    write_to_db = bool(payload.get("write_to_db", True))

    try:
        import asyncio
        res = asyncio.get_event_loop().run_until_complete(
            ingest_all_feeds_to_db(group_names=groups, limit=limit, write_to_db=write_to_db)
        )
        return _build_cors_response(jsonify({"ok": True, **res}))
    except RuntimeError:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(
            ingest_all_feeds_to_db(group_names=groups, limit=limit, write_to_db=write_to_db)
        )
        loop.close()
        return _build_cors_response(jsonify({"ok": True, **res}))
    except Exception as e:
        logger.error("rss_run error: %s\n%s", e, traceback.format_exc())
        return _build_cors_response(make_response(jsonify({"error": "RSS ingest failed"}), 500))

@app.route("/engine/run", methods=["POST", "OPTIONS"])
def engine_run():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))

    if enrich_and_store_alerts is None:
        return _build_cors_response(make_response(jsonify({"error": "Threat Engine unavailable"}), 503))

    payload = _json_request()
    region = payload.get("region")
    country = payload.get("country")
    city = payload.get("city")
    limit = int(payload.get("limit") or 1000)

    try:
        enriched = enrich_and_store_alerts(region=region, country=country, city=city, limit=limit)
        return _build_cors_response(jsonify({"ok": True, "count": len(enriched or []), "sample": (enriched or [])[:8]}))
    except Exception as e:
        logger.error("engine_run error: %s\n%s", e, traceback.format_exc())
        return _build_cors_response(make_response(jsonify({"error": "Threat Engine failed"}), 500))

# ---------- Alerts (richer payload for frontend) ----------
@app.route("/alerts/latest", methods=["GET"])
@login_required
def alerts_latest():
    # Paid gate removed - ALL authenticated users (FREE/PRO/ENTERPRISE) can access
    # Plan-based limits applied below
    email = get_logged_in_email()
    
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))

    # Get user's plan limits
    try:
        from plan_utils import get_plan_limits
        limits = get_plan_limits(email)
        plan_days_cap = limits.get("alerts_days", 7)
        plan_results_cap = limits.get("alerts_max_results", 30)
    except Exception as e:
        logger.warning("Failed to get plan limits: %s", e)
        plan_days_cap = 7
        plan_results_cap = 30

    # Parse and cap user-requested params
    try:
        limit_requested = int(request.args.get("limit", 20))
    except Exception:
        limit_requested = 20
    limit = max(1, min(limit_requested, plan_results_cap))  # Enforce plan cap

    try:
        days_requested = int(request.args.get("days", "7"))
    except Exception:
        days_requested = 7
    days = max(1, min(days_requested, plan_days_cap))  # Enforce plan cap

    region = request.args.get("region")
    country = request.args.get("country")
    city = request.args.get("city")
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    radius = request.args.get("radius", "100")  # km

    # Optional filters: severity, category, event_type, travel-only, and bbox
    severity_param = request.args.get("severity")
    severities = [s.strip().lower() for s in severity_param.split(",")] if severity_param else []

    category_param = request.args.get("category")
    categories = [c.strip().lower() for c in category_param.split(",")] if category_param else []

    event_type_param = request.args.get("event_type")
    event_types = [e.strip() for e in event_type_param.split(",")] if event_type_param else []

    travel_only = str(request.args.get("travel", "0")).lower() in ("1", "true", "yes", "y")

    # Optional bounding box (viewport) filter
    min_lat = request.args.get("min_lat")
    min_lon = request.args.get("min_lon")
    max_lat = request.args.get("max_lat")
    max_lon = request.args.get("max_lon")

    # Optional filters for frontend controls
    # severity: comma-separated labels (critical,high,medium,low)
    severity_param = request.args.get("severity")
    severities = [s.strip().lower() for s in severity_param.split(",")] if severity_param else []

    # category/subcategory: comma-separated
    category_param = request.args.get("category")
    categories = [c.strip().lower() for c in category_param.split(",")] if category_param else []

    # event_type from tags (best-effort, substring match on tags JSON text)
    event_type_param = request.args.get("event_type")
    event_types = [e.strip() for e in event_type_param.split(",")] if event_type_param else []

    where = []
    params = []
    
    # Time window filter (plan-capped days)
    where.append("published >= NOW() - make_interval(days => %s)")
    params.append(days)
    
    # Geographic filters
    if lat and lon:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            radius_f = float(radius)
            # Haversine distance filter (PostgreSQL)
            where.append(
                "("
                "  6371 * acos("
                "    cos(radians(%s)) * cos(radians(latitude)) * "
                "    cos(radians(longitude) - radians(%s)) + "
                "    sin(radians(%s)) * sin(radians(latitude))"
                "  ) <= %s"
                ")"
            )
            params.extend([lat_f, lon_f, lat_f, radius_f])
        except Exception as e:
            logger.warning(f"Invalid lat/lon/radius params: {e}")
    
    if region:
        # Keep original behavior: region param can match region OR city
        where.append("(region = %s OR city = %s)")
        params.extend([region, region])
    if country:
        where.append("country = %s")
        params.append(country)
    if city:
        where.append("city = %s")
        params.append(city)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    q = f"""
        SELECT
          uuid,
          published,
          source,
          title,
          link,
          region,
          country,
          city,
          category,
          subcategory,
          threat_level,
          threat_label,
          score,
          confidence,
          gpt_summary,
          summary,
          en_snippet,
          trend_direction,
          anomaly_flag,
          domains,
          tags,
          threat_score_components,
          source_kind,
          source_tag,
          latitude,
          longitude
        FROM alerts
        {where_sql}
        ORDER BY published DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)

    try:
        rows = fetch_all(q, tuple(params))
        
        # Transform to GeoJSON for frontend map compatibility
        features = []
        for row in (rows or []):
            if isinstance(row, dict):
                lat_val = row.get("latitude")
                lon_val = row.get("longitude")
            else:
                # Tuple row: latitude at index -2, longitude at index -1
                lat_val = row[-2] if len(row) >= 2 else None
                lon_val = row[-1] if len(row) >= 1 else None
            
            if lat_val is not None and lon_val is not None:
                properties = dict(row) if isinstance(row, dict) else {
                    "uuid": row[0] if len(row) > 0 else None,
                    "published": row[1] if len(row) > 1 else None,
                    "source": row[2] if len(row) > 2 else None,
                    "title": row[3] if len(row) > 3 else None,
                    "link": row[4] if len(row) > 4 else None,
                    "region": row[5] if len(row) > 5 else None,
                    "country": row[6] if len(row) > 6 else None,
                    "city": row[7] if len(row) > 7 else None,
                    "category": row[8] if len(row) > 8 else None,
                    "subcategory": row[9] if len(row) > 9 else None,
                    "threat_level": row[10] if len(row) > 10 else None,
                    "threat_label": row[11] if len(row) > 11 else None,
                    "score": row[12] if len(row) > 12 else None,
                    "confidence": row[13] if len(row) > 13 else None,
                }
                # Remove lat/lon from properties (they're in geometry)
                properties.pop("latitude", None)
                properties.pop("longitude", None)
                
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(lon_val), float(lat_val)]  # GeoJSON: [lon, lat]
                    },
                    "properties": properties
                })
        
        return _build_cors_response(jsonify({"ok": True, "items": rows, "features": features}))
    except Exception as e:
        logger.error("alerts_latest error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

# ---------- Public Alerts (limited, no auth) ----------
@app.route("/alerts/public/latest", methods=["GET"])
def alerts_public_latest():
    """Public version of latest alerts for maps. No auth, limited results.
    Supports same query params: lat, lon, radius, days, region, country, city, limit.
    Caps: limit<=50, days<=14.
    """
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))

    # Defensive caps
    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20
    limit = max(1, min(limit, 50))

    region = request.args.get("region")
    country = request.args.get("country")
    city = request.args.get("city")
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    radius = request.args.get("radius", "100")  # km
    days = request.args.get("days", "7")

    # Optional filters: severity, category, event_type (public variant)
    severity_param = request.args.get("severity")
    severities = [s.strip().lower() for s in severity_param.split(",")] if severity_param else []

    category_param = request.args.get("category")
    categories = [c.strip().lower() for c in category_param.split(",")] if category_param else []

    event_type_param = request.args.get("event_type")
    event_types = [e.strip() for e in event_type_param.split(",")] if event_type_param else []

    where = []
    params = []

    # Time window filter (cap days to 14)
    try:
        days_int = min(int(days), 14)
        where.append("published >= NOW() - make_interval(days => %s)")
        params.append(days_int)
    except Exception:
        pass

    # Geographic filters
    if lat and lon:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            radius_f = float(radius)
            where.append(
                "(" \
                "  6371 * acos(" \
                "    cos(radians(%s)) * cos(radians(latitude)) * " \
                "    cos(radians(longitude) - radians(%s)) + " \
                "    sin(radians(%s)) * sin(radians(latitude))" \
                "  ) <= %s" \
                ")"
            )
            params.extend([lat_f, lon_f, lat_f, radius_f])
        except Exception as e:
            logger.warning(f"Invalid lat/lon/radius params: {e}")

    if region:
        where.append("(region = %s OR city = %s)")
        params.extend([region, region])
    if country:
        where.append("country = %s")
        params.append(country)
    if city:
        where.append("city = %s")
        params.append(city)

    # Severity filter (match either threat_label or threat_level, case-insensitive)
    if severities:
        where.append("(LOWER(COALESCE(threat_label, '')) = ANY(%s) OR LOWER(COALESCE(threat_level, '')) = ANY(%s))")
        params.extend([severities, severities])

    # Category/Subcategory filter
    if categories:
        where.append("(LOWER(COALESCE(category, '')) = ANY(%s) OR LOWER(COALESCE(subcategory, '')) = ANY(%s))")
        params.extend([categories, categories])

    # Event type filter via tags text (best-effort contains match)
    if event_types:
        like_clauses = []
        for _ in event_types:
            like_clauses.append("tags::text ILIKE %s")
        where.append("(" + " OR ".join(like_clauses) + ")")
        # Match JSON substring for event_type values
        params.extend([f"%\"event_type\":\"{et}\"%" for et in event_types])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    q = f"""
        SELECT
          uuid,
          published,
          source,
          title,
          link,
          region,
          country,
          city,
          category,
          subcategory,
          threat_level,
          threat_label,
          score,
          confidence,
          gpt_summary,
          summary,
          en_snippet,
          trend_direction,
          anomaly_flag,
          domains,
          tags,
          threat_score_components,
          source_kind,
          source_tag,
          latitude,
          longitude
        FROM alerts
        {where_sql}
        ORDER BY published DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)

    try:
        rows = fetch_all(q, tuple(params))
        return _build_cors_response(jsonify({"ok": True, "items": rows}))
    except Exception as e:
        logger.error("alerts_public_latest error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

# ---------- Map Alerts (public, global, 30-day default) ----------
@app.route("/api/map-alerts", methods=["GET"])
def api_map_alerts():
    """Global map alerts endpoint for frontend maps.
    - Public, optional Bearer auth for extended limits
    - Defaults to 30-day window
    - Excludes ACLED by default
    - Supports optional params: days, limit, lat, lon, radius, region, country, city, sources, severity, category, event_type
    - Returns both raw items and GeoJSON features with risk_color and risk_radius
    """
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))
    
    # Optional auth - allow public access with lower caps, authenticated users get more
    auth_header = request.headers.get("Authorization", "")
    is_authenticated = auth_header.startswith("Bearer ") and len(auth_header) > 7

    # Defaults and caps
    try:
        days = int(request.args.get("days", 30))
    except Exception:
        days = 30
    # Allow days=0 for all historical data (no cap)
    if days < 0:
        days = 0

    try:
        limit = int(request.args.get("limit", 5000))
    except Exception:
        limit = 5000
    # Cap based on auth: 5000 public, 20000 authenticated
    max_limit = 20000 if is_authenticated else 5000
    limit = max(1, min(limit, max_limit))

    sources_param = request.args.get("sources")  # e.g. "gdelt,rss,news"
    if sources_param:
        sources = [s.strip().lower() for s in sources_param.split(",") if s.strip()]
    else:
        sources = ["gdelt", "rss", "news"]

    region = request.args.get("region")
    country = request.args.get("country")
    city = request.args.get("city")
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    radius = request.args.get("radius", "100")  # km

    # Filter parameters (severity, category, event_type, travel, bbox)
    severity_param = request.args.get("severity")
    severities = [s.strip().lower() for s in severity_param.split(",")] if severity_param else []
    
    category_param = request.args.get("category")
    categories = [c.strip().lower() for c in category_param.split(",")] if category_param else []
    
    event_type_param = request.args.get("event_type")
    event_types = [e.strip() for e in event_type_param.split(",")] if event_type_param else []
    
    travel_only = str(request.args.get("travel", "0")).lower() in ("1", "true", "yes", "y")
    
    # Bounding box parameters
    min_lat = request.args.get("min_lat")
    min_lon = request.args.get("min_lon")
    max_lat = request.args.get("max_lat")
    max_lon = request.args.get("max_lon")

    # Cache lookup (keyed by path, auth bucket, and sorted query args)
    try:
        cache_ttl = int(os.getenv("MAP_CACHE_TTL_SECONDS", "120"))
    except Exception:
        cache_ttl = 120
    try:
        args_key = tuple(sorted(request.args.items()))
        cache_key = f"{request.path}|auth={'1' if is_authenticated else '0'}|{args_key}"
        cached_payload = _MAP_CACHE.get(cache_key)
        if cached_payload:
            return _build_cors_response(jsonify(cached_payload))
    except Exception:
        pass

    where = []
    params = []

    # Quality filter: only show alerts with reliable geocoding (Tier 1)
    TIER1_METHODS = [
        'coordinates',           # Original RSS with coords
        'nlp_nominatim',        # Phase 2 NLP extraction + Nominatim
        'nlp_opencage',         # Phase 2 NLP extraction + OpenCage
        'production_stack',     # Phase 3 production geocoding stack
        'nominatim',            # Direct Nominatim geocoding
        'opencage',             # Direct OpenCage geocoding
        'db_cache',             # PostgreSQL cache hits (123 alerts)
        'legacy_precise',       # Backfilled unknown with city coords (250 alerts)
        'moderate',             # Moderate confidence extraction
    ]
    where.append("location_method = ANY(%s)")
    params.append(TIER1_METHODS)

    # Require valid coordinates for map display
    where.append("latitude IS NOT NULL")
    where.append("longitude IS NOT NULL")
    where.append("latitude BETWEEN -90 AND 90")
    where.append("longitude BETWEEN -180 AND 180")

    # Time window (use existing published column - skip if days=0 for all historical)
    if days > 0:
        where.append("published >= NOW() - make_interval(days => %s)")
        params.append(days)

    # Source filter (exclude acled by default)
    # NOTE: Disabled - source column contains domains (krebsonsecurity.com) not categories (rss)
    # if sources:
    #     where.append("LOWER(source) = ANY(%s)")
    #     params.append(sources)
    where.append("LOWER(source) <> 'acled'")

    # Optional geographic filters
    if lat and lon:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            radius_f = float(radius)
            where.append(
                "("
                "  6371 * acos("
                "    cos(radians(%s)) * cos(radians(latitude)) * "
                "    cos(radians(longitude) - radians(%s)) + "
                "    sin(radians(%s)) * sin(radians(latitude))"
                "  ) <= %s"
                ")"
            )
            params.extend([lat_f, lon_f, lat_f, radius_f])
        except Exception as e:
            logger.warning(f"Invalid lat/lon/radius params: {e}")

    # Bounding box filter (if provided)
    if min_lat and min_lon and max_lat and max_lon:
        try:
            min_lat_f = float(min_lat); max_lat_f = float(max_lat)
            min_lon_f = float(min_lon); max_lon_f = float(max_lon)
            where.append("latitude BETWEEN %s AND %s")
            where.append("longitude BETWEEN %s AND %s")
            params.extend([min_lat_f, max_lat_f, min_lon_f, max_lon_f])
        except Exception as e:
            logger.warning(f"Invalid bbox params: {e}")

    if region:
        where.append("(region = %s OR city = %s)")
        params.extend([region, region])
    if country:
        where.append("country = %s")
        params.append(country)
    if city:
        where.append("city = %s")
        params.append(city)

    # Severity filter
    if severities:
        where.append("(LOWER(COALESCE(threat_label, '')) = ANY(%s) OR LOWER(COALESCE(threat_level, '')) = ANY(%s))")
        params.extend([severities, severities])

    # Category filter
    if categories:
        where.append("(LOWER(COALESCE(category, '')) = ANY(%s) OR LOWER(COALESCE(subcategory, '')) = ANY(%s))")
        params.extend([categories, categories])

    # Event type filter (in tags JSON)
    if event_types:
        like_clauses = []
        for _ in event_types:
            like_clauses.append("tags::text ILIKE %s")
        where.append("(" + " OR ".join(like_clauses) + ")")
        params.extend([f"%\"event_type\":\"{et}\"%" for et in event_types])

    # Travel-only filter (requires tag travel_map_eligible true)
    if travel_only:
        where.append("tags::text ILIKE %s")
        params.append("%\"travel_map_eligible\": true%")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    q = f"""
        SELECT
          uuid,
          published,
          source,
          title,
          link,
          region,
          country,
          city,
          category,
          subcategory,
          threat_level,
          threat_label,
          score,
          confidence,
          gpt_summary,
          summary,
          en_snippet,
          trend_direction,
          anomaly_flag,
          domains,
          tags,
          threat_score_components,
          source_kind,
          source_tag,
          latitude,
          longitude
        FROM alerts
        {where_sql}
        ORDER BY published DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)

    try:
        rows = fetch_all(q, tuple(params))

        # Build GeoJSON features with consistent properties for maps
        features = []
        for row in (rows or []):
            # rows are dicts via fetch_all
            lat_val = row.get("latitude")
            lon_val = row.get("longitude")
            if lat_val is None or lon_val is None:
                continue
            properties = dict(row)
            properties.pop("latitude", None)
            properties.pop("longitude", None)
            
            # Add frontend-expected fields
            properties["lat"] = float(lat_val)
            properties["lon"] = float(lon_val)
            
            # Preferred display summary for popups (fallback chain: gpt_summary -> summary -> en_snippet -> title)
            properties["display_summary"] = (
                properties.get("gpt_summary") 
                or properties.get("summary") 
                or properties.get("en_snippet") 
                or properties.get("title") 
                or "No description available"
            )
            
            # Compute risk_color from severity
            severity = (properties.get("threat_label") or properties.get("threat_level") or "medium").lower()
            severity_colors = {
                "critical": "#DC2626",
                "high": "#EA580C",
                "medium": "#F59E0B",
                "low": "#10B981"
            }
            properties["risk_color"] = severity_colors.get(severity, severity_colors["medium"])
            
            # Compute risk_radius: use 0 for city-level, 200000m (200km) for country-level
            properties["risk_radius"] = 0 if properties.get("city") else 200000
            
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lon_val), float(lat_val)]},
                "properties": properties
            })

        payload = {
            "ok": True,
            "items": rows,
            "features": features,
            "meta": {"days": days, "limit": limit, "sources": sources, "filters": {
                "severity": severities, "category": categories, "event_type": event_types, "travel": travel_only
            }}
        }
        try:
            if cache_ttl > 0:
                _MAP_CACHE.set(cache_key, payload, cache_ttl)
        except Exception:
            pass
        return _build_cors_response(jsonify(payload))
    except Exception as e:
        logger.error("/api/map-alerts error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

# ---------- Map Alerts Aggregation (for zoom < 5 or mid-zoom regions) ----------
@app.route("/api/map-alerts/aggregates", methods=["GET"])
def api_map_alerts_aggregates():
    """Country, region, or city-level aggregation for map zoom < 10.
    Returns: [{ country|region|city(+country), count, avg_score, severity, lat, lon, radius }]
    Params: same as /api/map-alerts plus optional by=country|region|city
    - by=country (default): country-level rollups for zoom < 5
    - by=region: region-level rollups for zoom 5-10
    - by=city: city-level rollups for zoom >= 10 or dense areas
    """
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))
    
    # Optional auth
    auth_header = request.headers.get("Authorization", "")
    is_authenticated = auth_header.startswith("Bearer ") and len(auth_header) > 7

    # Defaults and caps
    try:
        days = int(request.args.get("days", 30))
    except Exception:
        days = 30
    # Allow days=0 for all historical data (no cap)
    if days < 0:
        days = 0

    sources_param = request.args.get("sources")
    if sources_param:
        sources = [s.strip().lower() for s in sources_param.split(",") if s.strip()]
    else:
        sources = ["gdelt", "rss", "news"]

    # Aggregation level: country (default), region, or city
    by = request.args.get("by", "country").lower()
    if by not in ["country", "region", "city"]:
        by = "country"
    
    severity_param = request.args.get("severity")
    severities = [s.strip().lower() for s in severity_param.split(",")] if severity_param else []

    category_param = request.args.get("category")
    categories = [c.strip().lower() for c in category_param.split(",")] if category_param else []

    event_type_param = request.args.get("event_type")
    event_types = [e.strip() for e in event_type_param.split(",")] if event_type_param else []

    # Travel-only filter
    travel_only = str(request.args.get("travel", "0")).lower() in ("1", "true", "yes", "y")

    # Optional bounding box (viewport) filter
    min_lat = request.args.get("min_lat")
    min_lon = request.args.get("min_lon")
    max_lat = request.args.get("max_lat")
    max_lon = request.args.get("max_lon")

    # Cache lookup (keyed by path, auth bucket, and sorted query args)
    try:
        agg_cache_ttl = int(os.getenv("MAP_AGG_CACHE_TTL_SECONDS", "180"))
    except Exception:
        agg_cache_ttl = 180
    try:
        args_key = tuple(sorted(request.args.items()))
        cache_key = f"{request.path}|auth={'1' if is_authenticated else '0'}|{args_key}"
        cached_payload = _AGG_CACHE.get(cache_key)
        if cached_payload:
            return _build_cors_response(jsonify(cached_payload))
    except Exception:
        pass

    where = []
    params = []

    # Quality filter: only show alerts with reliable geocoding (Tier 1)
    TIER1_METHODS = [
        'coordinates',           # Original RSS with coords
        'nlp_nominatim',        # Phase 2 NLP extraction + Nominatim
        'nlp_opencage',         # Phase 2 NLP extraction + OpenCage
        'production_stack',     # Phase 3 production geocoding stack
        'nominatim',            # Direct Nominatim geocoding
        'opencage',             # Direct OpenCage geocoding
        'db_cache',             # PostgreSQL cache hits (123 alerts)
        'legacy_precise',       # Backfilled unknown with city coords (250 alerts)
        'moderate',             # Moderate confidence extraction
    ]
    where.append("location_method = ANY(%s)")
    params.append(TIER1_METHODS)

    # Require valid coordinates for map display
    where.append("latitude IS NOT NULL")
    where.append("longitude IS NOT NULL")
    where.append("latitude BETWEEN -90 AND 90")
    where.append("longitude BETWEEN -180 AND 180")

    # Time window (use existing published column - skip if days=0 for all historical)
    if days > 0:
        where.append("published >= NOW() - make_interval(days => %s)")
        params.append(days)

    # Source filter (exclude acled)
    # NOTE: Disabled - source column contains domains (krebsonsecurity.com) not categories (rss)
    # if sources:
    #     where.append("LOWER(source) = ANY(%s)")
    #     params.append(sources)
    where.append("LOWER(source) <> 'acled'")

    # Severity filter
    if severities:
        where.append("(LOWER(COALESCE(threat_label, '')) = ANY(%s) OR LOWER(COALESCE(threat_level, '')) = ANY(%s))")
        params.extend([severities, severities])

    # Category filter
    if categories:
        where.append("(LOWER(COALESCE(category, '')) = ANY(%s) OR LOWER(COALESCE(subcategory, '')) = ANY(%s))")
        params.extend([categories, categories])

    # Event type filter
    if event_types:
        like_clauses = []
        for _ in event_types:
            like_clauses.append("tags::text ILIKE %s")
        where.append("(" + " OR ".join(like_clauses) + ")")
        params.extend([f"%\"event_type\":\"{et}\"%" for et in event_types])

    # Travel-only filter (requires tag travel_map_eligible true)
    if travel_only:
        where.append("tags::text ILIKE %s")
        params.append("%\"travel_map_eligible\": true%")

    # Bounding box filter (if provided)
    if min_lat and min_lon and max_lat and max_lon:
        try:
            min_lat_f = float(min_lat); max_lat_f = float(max_lat)
            min_lon_f = float(min_lon); max_lon_f = float(max_lon)
            where.append("latitude BETWEEN %s AND %s")
            where.append("longitude BETWEEN %s AND %s")
            params.extend([min_lat_f, max_lat_f, min_lon_f, max_lon_f])
        except Exception as e:
            logger.warning(f"Invalid bbox params (aggregates): {e}")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    # Build aggregation query based on level
    if by == "city":
        q = f"""
            SELECT
              city,
              country,
              COUNT(*) as alert_count,
              AVG(CAST(score AS FLOAT)) as avg_score,
              AVG(latitude) as center_lat,
              AVG(longitude) as center_lon,
              MAX(COALESCE(threat_label, threat_level, 'medium')) as max_severity,
              STDDEV(latitude) as lat_spread,
              STDDEV(longitude) as lon_spread
            FROM alerts
            {where_sql}
              AND city IS NOT NULL
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
            GROUP BY city, country
            ORDER BY alert_count DESC
        """
    else:
        # Aggregate by country or region
        if by == "region":
            group_field = "COALESCE(region, country)"
        else:
            group_field = "country"

        q = f"""
            SELECT
              {group_field} as grouping,
              COUNT(*) as alert_count,
              AVG(CAST(score AS FLOAT)) as avg_score,
              AVG(latitude) as center_lat,
              AVG(longitude) as center_lon,
              MAX(COALESCE(threat_label, threat_level, 'medium')) as max_severity,
              STDDEV(latitude) as lat_spread,
              STDDEV(longitude) as lon_spread
            FROM alerts
            {where_sql}
              AND {group_field} IS NOT NULL
              AND latitude IS NOT NULL
              AND longitude IS NOT NULL
            GROUP BY {group_field}
            ORDER BY alert_count DESC
        """

    try:
        rows = fetch_all(q, tuple(params))

        aggregates = []
        features = []
        for row in (rows or []):
            count = int(row.get("alert_count") or 0)
            avg_score = float(row.get("avg_score") or 0.5)
            lat = float(row.get("center_lat") or 0)
            lon = float(row.get("center_lon") or 0)
            severity = (row.get("max_severity") or "medium").lower()
            lat_spread = float(row.get("lat_spread") or 1.0)
            lon_spread = float(row.get("lon_spread") or 1.0)

            # Calculate uncertainty radius based on coordinate spread
            # 1 degree latitude ≈ 111 km, return in meters for frontend
            radius_km = max(10 if by == "city" else 50, min(400, (lat_spread + lon_spread) * 111 / 2))
            radius_meters = radius_km * 1000

            agg_item = {
                "count": count,
                "avg_score": round(avg_score, 2),
                "severity": severity,
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "radius": int(radius_meters)
            }

            if by == "city":
                agg_item["city"] = row.get("city") or "Unknown"
                agg_item["country"] = row.get("country") or None
            elif by == "region":
                agg_item["region"] = row.get("grouping") or "Unknown"
            else:
                agg_item["country"] = row.get("grouping") or "Unknown"

            aggregates.append(agg_item)
            
            # Also create GeoJSON feature for Leaflet rendering
            severity_colors = {
                "critical": "#DC2626",
                "high": "#EA580C", 
                "medium": "#F59E0B",
                "low": "#10B981",
                "armed conflict": "#DC2626",
                "material conflict": "#EA580C"
            }
            # Build a stable group label for popup titles
            if by == "city":
                _city = row.get("city") or "Unknown"
                _country = row.get("country")
                group_label = f"{_city}, {_country}" if _country else _city
            elif by == "region":
                group_label = row.get("grouping") or "Unknown"
            else:
                group_label = row.get("grouping") or "Unknown"
            safe_title = f"{group_label} - {count} alerts"
            
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(lon, 4), round(lat, 4)]
                },
                "properties": {
                    "count": count,
                    "avg_score": round(avg_score, 2),
                    "severity": severity,
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    "radius": int(radius_meters),
                    "risk_color": severity_colors.get(severity.lower(), severity_colors["medium"]),
                    "risk_radius": int(radius_meters),
                    "display_summary": f"{count} alerts in this area",
                    "title": safe_title
                }
            }
            
            # Copy location fields to properties
            if by == "city":
                feature["properties"]["city"] = row.get("city") or "Unknown"
                feature["properties"]["country"] = row.get("country") or None
            elif by == "region":
                feature["properties"]["region"] = row.get("grouping") or "Unknown"
            else:
                feature["properties"]["country"] = row.get("grouping") or "Unknown"
            # Final guards to ensure popup consistency
            props = feature["properties"]
            if not props.get("title"):
                props["title"] = safe_title
            rc = props.get("risk_color")
            if not rc or not isinstance(rc, str) or not rc.startswith("#"):
                props["risk_color"] = severity_colors.get(severity.lower(), "#F59E0B")
            
            features.append(feature)
        
        # Debug: count pre-filter rows to diagnose empty results
        debug_pre_filter = fetch_all(f"SELECT COUNT(*) as cnt FROM alerts WHERE latitude IS NOT NULL AND longitude IS NOT NULL", tuple())
        debug_recent = fetch_all(f"SELECT COUNT(*) as cnt FROM alerts WHERE published >= NOW() - INTERVAL '{days} days' AND latitude IS NOT NULL AND longitude IS NOT NULL", tuple())
        debug_source = fetch_all(f"SELECT LOWER(source) as src, COUNT(*) as cnt FROM alerts WHERE published >= NOW() - INTERVAL '{days} days' AND latitude IS NOT NULL AND longitude IS NOT NULL GROUP BY LOWER(source) LIMIT 10", tuple())
        
        # Log sample feature for frontend debugging
        if features:
            logger.info(f"[AGGREGATES] Sample feature structure: {features[0]}")
            logger.info(f"[AGGREGATES] Total features: {len(features)}, Total aggregates: {len(aggregates)}")
        
        payload = {
            "ok": True,
            "aggregates": aggregates,
            "features": features,
            "meta": {"days": days, "sources": sources, "by": by, "filters": {
                "severity": severities, "category": categories, "event_type": event_types, "travel": travel_only
            }},
            "debug": {
                "total_with_coords": debug_pre_filter[0]['cnt'] if debug_pre_filter else 0,
                "recent_with_coords": debug_recent[0]['cnt'] if debug_recent else 0,
                "sources_breakdown": [{"source": r['src'], "count": r['cnt']} for r in (debug_source or [])],
                "sample_feature": features[0] if features else None,
                "sample_aggregate": aggregates[0] if aggregates else None
            }
        }
        try:
            if agg_cache_ttl > 0:
                _AGG_CACHE.set(cache_key, payload, agg_cache_ttl)
        except Exception:
            pass
        return _build_cors_response(jsonify(payload))
    except Exception as e:
        logger.error("/api/map-alerts/aggregates error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Aggregation query failed"}), 500))

# ---------- Analytics Endpoints ----------
@app.route("/analytics/timeline", methods=["GET"])
@login_required
def analytics_timeline():
    """Return time-series aggregation of alerts for timeline chart.
    Respects user's timeline_days plan limit.
    Returns: { series: [{ date: "YYYY-MM-DD", incidents: number }], escalation?: {...} }
    """
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "Database not available"}), 503))
    
    try:
        from plan_utils import get_plan_limits
        email = g.user_email
        limits = get_plan_limits(email) or {}
        timeline_days = limits.get("timeline_days", 7)
        
        # Query alerts grouped by day within user's plan window
        q = """
            SELECT 
                DATE(published) as incident_date,
                COUNT(*) as incident_count
            FROM alerts
            WHERE published >= NOW() - make_interval(days => %s)
            GROUP BY DATE(published)
            ORDER BY incident_date ASC
        """
        rows = fetch_all(q, (timeline_days,))
        
        series = []
        for row in (rows or []):
            if isinstance(row, dict):
                series.append({
                    "date": str(row.get("incident_date", "")),
                    "incidents": int(row.get("incident_count", 0))
                })
            else:
                series.append({
                    "date": str(row[0]) if row[0] else "",
                    "incidents": int(row[1]) if len(row) > 1 else 0
                })
        
        # Optional: Detect escalation trend (simple heuristic)
        escalation = None
        if len(series) >= 3:
            recent_avg = sum(s["incidents"] for s in series[-3:]) / 3
            older_avg = sum(s["incidents"] for s in series[:-3]) / max(len(series) - 3, 1)
            if recent_avg > older_avg * 1.5:
                escalation = {"level": "rising", "trend": "up"}
        
        return _build_cors_response(jsonify({
            "ok": True,
            "series": series,
            "escalation": escalation,
            "window_days": timeline_days
        }))
        
    except Exception as e:
        logger.error("analytics_timeline error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Timeline query failed"}), 500))

# ---------- Stats Overview Endpoint ----------
STATS_OVERVIEW_CACHE_SECONDS = int(os.getenv("STATS_OVERVIEW_CACHE_SECONDS", "120"))
_STATS_OVERVIEW_CACHE = {}

@app.route("/api/stats/overview", methods=["GET"])
@login_required
def stats_overview():
    """Return consolidated stats for dashboard.
    Query params:
      days=7|30|90 (optional) controls window for weekly_trends, severity_breakdown, top_regions
      Plan-based limits: FREE=7, PRO=30, ENTERPRISE/VIP=90
    Response:
      {
        ok, updated_at, threats_7d, threats_30d, trend_7d,
        active_monitors, tracked_locations, chat_messages_month,
        weekly_trends: [{date, count}], top_regions: [{region,count,percentage}],
        severity_breakdown: {critical, high, medium, low, critical_pct, high_pct, medium_pct, low_pct, total},
        window_days, max_window_days (plan limit)
      }
    """
    if fetch_all is None or fetch_one is None:
        return _build_cors_response(make_response(jsonify({"error": "Database unavailable"}), 503))

    try:
        # Get user plan limits
        email = get_logged_in_email()
        from plan_utils import get_plan_limits
        limits = get_plan_limits(email) or {}
        max_window_days = limits.get("statistics_days", 7)
        
        # Validate days param against plan limit
        days_param = request.args.get("days", str(max_window_days))
        try:
            requested_days = int(days_param)
        except ValueError:
            requested_days = max_window_days
        
        # Clamp to plan limit
        window_days = min(requested_days, max_window_days)
        if window_days not in (7, 30, 90):
            # Round to nearest valid window
            if window_days <= 7:
                window_days = 7
            elif window_days <= 30:
                window_days = 30
            else:
                window_days = 90

        # Simple cache key with email for user-specific data
        cache_key = f"stats:{email}:{window_days}"
        now_ts = int(time.time())
        cached = _STATS_OVERVIEW_CACHE.get(cache_key)
        if cached and (now_ts - cached.get("cached_at", 0)) < STATS_OVERVIEW_CACHE_SECONDS:
            return _build_cors_response(jsonify(cached["payload"]))

        # Threat counts (fixed 7d / 30d regardless of window_days)
        q_threat_7d = "SELECT COUNT(*) AS cnt FROM alerts WHERE published >= NOW() - make_interval(days => 7)"
        q_threat_30d = "SELECT COUNT(*) AS cnt FROM alerts WHERE published >= NOW() - make_interval(days => 30)"
        row_7d = fetch_one(q_threat_7d, ()) or {}
        row_30d = fetch_one(q_threat_30d, ()) or {}
        threats_7d = int(row_7d.get("cnt", 0)) if isinstance(row_7d, dict) else int(row_7d[0]) if row_7d else 0
        threats_30d = int(row_30d.get("cnt", 0)) if isinstance(row_30d, dict) else int(row_30d[0]) if row_30d else 0

        # Trend: Compare current 7d vs previous 7d window
        q_prev_7d = (
            "SELECT COUNT(*) AS cnt FROM alerts WHERE published >= NOW() - make_interval(days => 14) "
            "AND published < NOW() - make_interval(days => 7)"
        )
        prev_row = fetch_one(q_prev_7d, ()) or {}
        prev_cnt = int(prev_row.get("cnt", 0)) if isinstance(prev_row, dict) else int(prev_row[0]) if prev_row else 0
        trend_7d = 0
        if prev_cnt > 0:
            trend_7d = round(((threats_7d - prev_cnt) / prev_cnt) * 100)

        # Weekly (or 30-day) trends: build full sequence including missing days
        q_trends = (
            "SELECT DATE(published) AS d, COUNT(*) AS c FROM alerts "
            "WHERE published >= NOW() - make_interval(days => %s) "
            "GROUP BY DATE(published) ORDER BY d ASC"
        )
        trend_rows = fetch_all(q_trends, (window_days,)) or []
        # Map existing counts by date
        counts_by_date = {}
        for r in trend_rows:
            if isinstance(r, dict):
                counts_by_date[str(r.get("d"))] = int(r.get("c", 0))
            else:
                counts_by_date[str(r[0])] = int(r[1]) if len(r) > 1 else 0

        # Generate complete date list (chronological)
        today = datetime.utcnow().date()
        date_list = [today - timedelta(days=offset) for offset in reversed(range(window_days))]
        weekly_trends = [
            {"date": d.isoformat(), "count": counts_by_date.get(d.isoformat(), 0)}
            for d in date_list
        ]

        # Severity breakdown for window_days with percentages
        q_severity = (
            "SELECT threat_level, COUNT(*) AS cnt FROM alerts "
            "WHERE published >= NOW() - make_interval(days => %s) GROUP BY threat_level"
        )
        severity_rows = fetch_all(q_severity, (window_days,)) or []
        severity_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in severity_rows:
            level = (r.get("threat_level") if isinstance(r, dict) else r[0]) or ""
            cnt = int(r.get("cnt") if isinstance(r, dict) else r[1])
            key = level.lower()
            if key in severity_breakdown:
                severity_breakdown[key] += cnt
            else:
                # Treat unknown/minor as low bucket
                severity_breakdown["low"] += cnt
        
        # Calculate percentages for severity
        total_severity = sum(severity_breakdown.values())
        severity_breakdown["total"] = total_severity
        if total_severity > 0:
            severity_breakdown["critical_pct"] = round((severity_breakdown["critical"] / total_severity) * 100, 1)
            severity_breakdown["high_pct"] = round((severity_breakdown["high"] / total_severity) * 100, 1)
            severity_breakdown["medium_pct"] = round((severity_breakdown["medium"] / total_severity) * 100, 1)
            severity_breakdown["low_pct"] = round((severity_breakdown["low"] / total_severity) * 100, 1)
        else:
            severity_breakdown["critical_pct"] = 0.0
            severity_breakdown["high_pct"] = 0.0
            severity_breakdown["medium_pct"] = 0.0
            severity_breakdown["low_pct"] = 0.0

        # Top regions within window_days (limit 5)
        q_regions = (
            "SELECT COALESCE(region, 'Unknown') AS region, COUNT(*) AS cnt FROM alerts "
            "WHERE published >= NOW() - make_interval(days => %s) GROUP BY region ORDER BY cnt DESC LIMIT 5"
        )
        region_rows = fetch_all(q_regions, (window_days,)) or []
        top_regions = []
        total_regions = 0
        for r in region_rows:
            region = r.get("region") if isinstance(r, dict) else r[0]
            cnt = int(r.get("cnt") if isinstance(r, dict) else r[1])
            total_regions += cnt
            top_regions.append({"region": region or "Unknown", "count": cnt})
        for tr in top_regions:
            pct = 0.0
            if total_regions > 0:
                pct = round((tr["count"] / total_regions) * 100, 2)
            tr["percentage"] = pct

        # Active monitors (traveler_profiles active=true)
        q_monitors = "SELECT COUNT(*) AS cnt FROM traveler_profiles WHERE active = true"
        monitors_row = fetch_one(q_monitors, ()) or {}
        active_monitors = int(monitors_row.get("cnt", 0)) if isinstance(monitors_row, dict) else int(monitors_row[0]) if monitors_row else 0

        # Tracked locations: distinct locations from alerts with coordinates (within window_days)
        q_tracked = """
            SELECT COUNT(DISTINCT COALESCE(city, country)) AS cnt 
            FROM alerts 
            WHERE published >= NOW() - make_interval(days => %s)
            AND lat IS NOT NULL AND lon IS NOT NULL
        """
        tracked_row = fetch_one(q_tracked, (window_days,)) or {}
        tracked_locations = int(tracked_row.get("cnt", 0)) if isinstance(tracked_row, dict) else int(tracked_row[0]) if tracked_row else 0

        # Chat messages (current user month usage)
        email = get_logged_in_email()
        chat_messages_month = 0
        try:
            from plan_utils import get_usage
            usage = get_usage(email) or {}
            chat_messages_month = int(usage.get("chat_messages_used", 0))
        except Exception:
            pass

        payload = {
            "ok": True,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "threats_7d": threats_7d,
            "threats_30d": threats_30d,
            "trend_7d": trend_7d,
            "active_monitors": active_monitors,
            "tracked_locations": tracked_locations,
            "chat_messages_month": chat_messages_month,
            "weekly_trends": weekly_trends,
            "top_regions": top_regions,
            "severity_breakdown": severity_breakdown,
            "window_days": window_days,
            "max_window_days": max_window_days,
        }

        # Cache result
        _STATS_OVERVIEW_CACHE[cache_key] = {"cached_at": now_ts, "payload": payload}
        return _build_cors_response(jsonify(payload))
    except Exception as e:
        logger.error("stats_overview error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Stats overview failed"}), 500))

@app.route("/analytics/statistics", methods=["GET"])
@login_required
def analytics_statistics():
    """Return aggregated statistics for alerts within user's statistics_days window.
    Returns: { summary, distribution, regions, severity_percentiles, top_countries, avg_score }
    """
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "Database not available"}), 503))
    
    try:
        from plan_utils import get_plan_limits
        email = g.user_email
        limits = get_plan_limits(email) or {}
        statistics_days = limits.get("statistics_days", 7)
        
        # Summary stats by threat level
        summary_q = """
            SELECT 
                threat_level,
                COUNT(*) as count
            FROM alerts
            WHERE published >= NOW() - make_interval(days => %s)
            GROUP BY threat_level
        """
        summary_rows = fetch_all(summary_q, (statistics_days,))
        
        summary = {
            "total": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "unknown": 0
        }
        
        for row in (summary_rows or []):
            level = (row.get("threat_level") if isinstance(row, dict) else row[0]) or "unknown"
            count = int(row.get("count") if isinstance(row, dict) else row[1])
            level_key = level.lower() if level else "unknown"
            if level_key in summary:
                summary[level_key] = count
            summary["total"] += count
        
        # Distribution (clean copy without "total" and "unknown")
        distribution = {
            "critical": summary["critical"],
            "high": summary["high"],
            "medium": summary["medium"],
            "low": summary["low"]
        }
        
        # Regions with risk levels (based on avg score per country)
        regions_q = """
            SELECT 
                country,
                COUNT(*) as count,
                AVG(score) as avg_score
            FROM alerts
            WHERE published >= NOW() - make_interval(days => %s)
              AND country IS NOT NULL
              AND score IS NOT NULL
            GROUP BY country
            ORDER BY count DESC
            LIMIT 20
        """
        regions_rows = fetch_all(regions_q, (statistics_days,))
        
        regions = []
        for row in (regions_rows or []):
            if isinstance(row, dict):
                country = row.get("country", "Unknown")
                count = int(row.get("count", 0))
                score = float(row.get("avg_score", 0))
            else:
                country = row[0] if row[0] else "Unknown"
                count = int(row[1]) if len(row) > 1 else 0
                score = float(row[2]) if len(row) > 2 else 0.0
            
            # Categorize risk level based on average score
            if score >= 70:
                risk = "critical"
            elif score >= 50:
                risk = "high"
            elif score >= 30:
                risk = "medium"
            else:
                risk = "low"
            
            regions.append({
                "name": country,
                "risk": risk,
                "count": count,
                "avg_score": round(score, 2)
            })
        
        # Severity percentiles
        percentiles_q = """
            SELECT 
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY score) as p50,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY score) as p75,
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY score) as p90,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY score) as p95
            FROM alerts
            WHERE published >= NOW() - make_interval(days => %s)
              AND score IS NOT NULL
        """
        percentiles_row = fetch_all(percentiles_q, (statistics_days,))
        
        severity_percentiles = {
            "p50": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "p95": 0.0
        }
        
        if percentiles_row and len(percentiles_row) > 0:
            row = percentiles_row[0]
            if isinstance(row, dict):
                severity_percentiles["p50"] = round(float(row.get("p50", 0) or 0), 2)
                severity_percentiles["p75"] = round(float(row.get("p75", 0) or 0), 2)
                severity_percentiles["p90"] = round(float(row.get("p90", 0) or 0), 2)
                severity_percentiles["p95"] = round(float(row.get("p95", 0) or 0), 2)
            else:
                severity_percentiles["p50"] = round(float(row[0] or 0), 2)
                severity_percentiles["p75"] = round(float(row[1] or 0), 2)
                severity_percentiles["p90"] = round(float(row[2] or 0), 2)
                severity_percentiles["p95"] = round(float(row[3] or 0), 2)
        
        # Top countries (backward compatibility)
        top_countries = [{"country": r["name"], "count": r["count"]} for r in regions[:10]]
        
        # Average threat score
        avg_q = """
            SELECT AVG(score) as avg_score
            FROM alerts
            WHERE published >= NOW() - make_interval(days => %s)
              AND score IS NOT NULL
        """
        avg_row = fetch_all(avg_q, (statistics_days,))
        avg_score = 0.0
        if avg_row and len(avg_row) > 0:
            avg_val = avg_row[0].get("avg_score") if isinstance(avg_row[0], dict) else avg_row[0][0]
            avg_score = float(avg_val) if avg_val else 0.0
        
        return _build_cors_response(jsonify({
            "ok": True,
            "summary": summary,
            "distribution": distribution,
            "regions": regions,
            "severity_percentiles": severity_percentiles,
            "top_countries": top_countries,
            "avg_score": round(avg_score, 2),
            "window_days": statistics_days
        }))
        
    except Exception as e:
        logger.error("analytics_statistics error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Statistics query failed"}), 500))

# ---------- Alert Scoring Details ----------
@app.route("/alerts/<alert_uuid>/scoring", methods=["GET"])
@login_required
def alert_scoring_details(alert_uuid):
    """
    Get detailed threat scoring breakdown for a specific alert.
    Returns threat_score_components with SOCMINT and other scoring factors.
    
    Example: GET /alerts/abc-123/scoring
    """
    if require_paid_feature is None:
        return _build_cors_response(make_response(jsonify({"error": "Plan gate unavailable"}), 503))
    email = get_logged_in_email()
    ok, msg = require_paid_feature(email)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 403))

    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))

    q = """
        SELECT
          uuid,
          title,
          score,
          threat_level,
          threat_label,
          confidence,
          threat_score_components,
          category,
          published
        FROM alerts
        WHERE uuid = %s
    """

    try:
        row = fetch_one(q, (alert_uuid,))
        if not row:
            return _build_cors_response(make_response(jsonify({"error": "Alert not found"}), 404))
        
        # Convert row tuple to dict if needed
        if isinstance(row, tuple):
            keys = ['uuid', 'title', 'score', 'threat_level', 'threat_label', 
                   'confidence', 'threat_score_components', 'category', 'published']
            result = dict(zip(keys, row))
        else:
            result = dict(row)
        
        # Parse threat_score_components if it's a string
        components = result.get('threat_score_components')
        if isinstance(components, str):
            import json
            try:
                result['threat_score_components'] = json.loads(components)
            except Exception:
                pass
        
        return _build_cors_response(jsonify({"ok": True, "alert": result}))
    except Exception as e:
        logger.error("alert_scoring_details error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

# ---------- Alert Feedback ----------
def _ensure_alert_feedback_table():
    """
    Creates the alert_feedback table if not present.
    Columns:
      id           BIGSERIAL PK
      alert_id     TEXT (uuid or any identifying string from alerts)
      user_email   TEXT (if logged in; else NULL)
      text         TEXT (user feedback)
      meta         JSONB (optional client metadata)
      created_at   TIMESTAMPTZ default now()
    """
    sql = """
    CREATE TABLE IF NOT EXISTS alert_feedback (
      id          BIGSERIAL PRIMARY KEY,
      alert_id    TEXT,
      user_email  TEXT,
      text        TEXT NOT NULL,
      meta        JSONB,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    try:
        if execute is not None:
            execute(sql)
            return
    except Exception as e:
        logger.info("db_utils.execute failed creating alert_feedback, falling back: %s", e)

    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor() as cur:
                cur.execute(sql)
                conn.commit()
        except Exception as e:
            logger.error("Failed to create alert_feedback via psycopg2: %s", e)


@app.route("/feedback/alert", methods=["POST", "OPTIONS"])
def feedback_alert():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))

    _ensure_alert_feedback_table()
    payload = _json_request()

    alert_id = (payload.get("alert_id") or "").strip() or None
    text = (payload.get("text") or "").strip()
    meta = payload.get("meta")  # optional dict with ui_version, filters, etc.

    if not text:
        return _build_cors_response(make_response(jsonify({"error": "Missing text"}), 400))
    # keep it sane
    if len(text) > 4000:
        text = text[:4000]

    # Try to capture who sent it (JWT if present; else fall back)
    user_email = None
    try:
        if get_logged_in_email:
            user_email = get_logged_in_email()
    except Exception:
        pass
    if not user_email:
        hdr_email = request.headers.get("X-User-Email")
        if hdr_email:
            user_email = hdr_email.strip().lower()

    # Insert (db_utils first, then psycopg2)
    try:
        if execute is not None:
            try:
                m = Json(meta) if isinstance(meta, dict) else None
            except Exception:
                m = meta if isinstance(meta, dict) else None
            execute(
                "INSERT INTO alert_feedback (alert_id, user_email, text, meta) VALUES (%s, %s, %s, %s)",
                (alert_id, user_email, text, m),
            )
            return _build_cors_response(jsonify({"ok": True}))
    except Exception as e:
        logger.info("feedback_alert via db_utils failed, falling back: %s", e)

    if _psql_ok and DATABASE_URL:
        try:
            with _psql_conn() as conn, conn.cursor() as cur:
                try:
                    m = Json(meta) if isinstance(meta, dict) else None
                except Exception:
                    m = meta if isinstance(meta, dict) else None
                cur.execute(
                    "INSERT INTO alert_feedback (alert_id, user_email, text, meta) VALUES (%s, %s, %s, %s)",
                    (alert_id, user_email, text, m),
                )
                conn.commit()
            return _build_cors_response(jsonify({"ok": True}))
        except Exception as e:
            logger.exception("feedback_alert psycopg2 failed: %s", e)
            return _build_cors_response(make_response(jsonify({"error": "Feedback store failed"}), 500))

    return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))

# ---------- Real-time Threat Search (Moonshot primary) ----------
@app.route("/search/threats", methods=["POST", "OPTIONS"])
def search_threats():
    """Real-time threat intelligence search using Kimi Moonshot"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))

    try:
        from llm_router import route_llm_search
    except Exception:
        return _build_cors_response(make_response(jsonify({"error": "Search service unavailable"}), 503))

    payload = _json_request()
    query = (payload.get("query") or "").strip()
    context = payload.get("context", "")

    if not query:
        return _build_cors_response(make_response(jsonify({"error": "Query required"}), 400))

    # Enforce reasonable length for search
    if len(query) > 500:
        return _build_cors_response(make_response(jsonify({"error": "Query too long (max 500 chars)"}), 400))

    # If limiter is present, rate-limit this endpoint (decorator style would be cleaner;
    # using programmatic call here to avoid redeclaring route)
    if limiter:
        try:
            # This programmatic call simply checks/enforces throttle; if limit exceeded flask-limiter will raise
            limiter._check_request_limit(request, scope="global", limit_value=SEARCH_RATE)
        except Exception:
            # If limiter internals differ or storage not configured, just continue
            pass

    try:
        # Use dedicated search routing with Moonshot primary
        result, model_used = route_llm_search(query, context)

        return _build_cors_response(jsonify({
            "ok": True,
            "query": query,
            "result": result,
            "model": model_used,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }))

    except Exception as e:
        logger.error("search_threats error: %s\n%s", e, traceback.format_exc())
        return _build_cors_response(make_response(jsonify({"error": "Search failed"}), 500))

# ---------- Batch Alert Processing (128k context) ----------
@app.route("/alerts/batch_enrich", methods=["POST", "OPTIONS"])
def batch_enrich_alerts():
    """Batch process multiple alerts using Moonshot's 128k context window"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))

    try:
        from llm_router import route_llm_batch
    except Exception:
        return _build_cors_response(make_response(jsonify({"error": "Batch processing unavailable"}), 503))

    payload = _json_request()
    limit = min(int(payload.get("limit", 10)), 20)  # Max 20 alerts per batch

    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "Database unavailable"}), 503))

    # Programmatic rate check if limiter present
    if limiter:
        try:
            limiter._check_request_limit(request, scope="global", limit_value=BATCH_ENRICH_RATE)
        except Exception:
            pass

    try:
        # Get recent unprocessed alerts for batch enrichment
        alerts = fetch_all("""
            SELECT uuid, title, summary, city, country, link, published
            FROM alerts 
            WHERE gpt_summary IS NULL OR gpt_summary = ''
            ORDER BY published DESC 
            LIMIT %s
        """, (limit,))

        if not alerts:
            return _build_cors_response(jsonify({
                "ok": True,
                "message": "No alerts need batch processing",
                "processed": 0
            }))

        # Convert to dict format for processing
        alerts_batch = [dict(alert) for alert in alerts]

        # Process batch with 128k context
        try:
            batch_result = route_llm_batch(alerts_batch, context_window="128k")
            
            return _build_cors_response(jsonify({
                "ok": True,
                "message": f"Batch processing completed",
                "processed": len(alerts_batch),
                "result": batch_result
            }))
            
        except Exception as batch_error:
            logger.error(f"Batch processing error: {batch_error}")
            return _build_cors_response(make_response(jsonify({
                "error": f"Batch processing failed: {str(batch_error)}"
            }), 500))
            
    except Exception as e:
        logger.error(f"Batch endpoint error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

# ---------- Monitoring Endpoints (Coverage / Metrics) ----------
@app.route("/api/monitoring/coverage", methods=["GET"])  # lightweight, no auth for now
def get_coverage_report():
    try:
        from coverage_monitor import get_coverage_monitor
        monitor = get_coverage_monitor()
        report = monitor.get_comprehensive_report()
        return _build_cors_response(jsonify(report))
    except Exception as e:
        logger.error(f"/api/monitoring/coverage error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Monitoring unavailable"}), 500))


@app.route("/api/monitoring/gaps", methods=["GET"])  # lightweight, no auth for now
def get_coverage_gaps_endpoint():
    try:
        from coverage_monitor import get_coverage_monitor
        monitor = get_coverage_monitor()
        min_alerts = int(request.args.get("min_alerts_7d", 5))
        max_age = int(request.args.get("max_age_hours", 24))
        gaps = monitor.get_coverage_gaps(min_alerts_7d=min_alerts, max_age_hours=max_age)
        return _build_cors_response(jsonify({
            "gaps": gaps,
            "count": len(gaps),
            "parameters": {"min_alerts_7d": min_alerts, "max_age_hours": max_age},
        }))
    except Exception as e:
        logger.error(f"/api/monitoring/gaps error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))


@app.route("/api/monitoring/stats", methods=["GET"])  # lightweight, no auth for now
def get_monitoring_stats():
    try:
        from coverage_monitor import get_coverage_monitor
        monitor = get_coverage_monitor()
        return _build_cors_response(jsonify({
            "location_extraction": monitor.get_location_extraction_stats(),
            "advisory_gating": monitor.get_advisory_gating_stats(),
        }))
    except Exception as e:
        logger.error(f"/api/monitoring/stats error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))


# ---------- Dashboard-Friendly Endpoints (compact JSON) ----------
@app.route("/api/monitoring/dashboard/summary", methods=["GET", "OPTIONS"])  # compact payload for Next.js
def monitoring_dashboard_summary():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    try:
        from coverage_monitor import get_coverage_monitor
        mon = get_coverage_monitor()
        report = mon.get_comprehensive_report()
        geo = report.get("geographic_coverage", {})
        prov = geo.get("provenance", {})
        return _build_cors_response(jsonify({
            "timestamp": report.get("timestamp"),
            "total_locations": geo.get("total_locations", 0),
            "covered_locations": geo.get("covered_locations", 0),
            "coverage_gaps": geo.get("coverage_gaps", 0),
            "total_alerts_7d": prov.get("total_alerts_7d", 0),
            "synthetic_alerts_7d": prov.get("synthetic_alerts_7d", 0),
            "synthetic_ratio_7d": prov.get("synthetic_ratio_7d", 0),
        }))
    except Exception as e:
        logger.error(f"/api/monitoring/dashboard/summary error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Summary unavailable"}), 500))


@app.route("/api/monitoring/dashboard/top_gaps", methods=["GET", "OPTIONS"])  # compact list
def monitoring_dashboard_top_gaps():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    try:
        from coverage_monitor import get_coverage_monitor
        mon = get_coverage_monitor()
        limit = max(1, min(int(request.args.get("limit", 5)), 50))
        gaps = mon.get_coverage_gaps(
            min_alerts_7d=int(request.args.get("min_alerts_7d", 5)),
            max_age_hours=int(request.args.get("max_age_hours", 24)),
        )
        # Already sorted ascending by alerts; slice
        data = [{
            "country": g.get("country"),
            "region": g.get("region"),
            "issues": g.get("issues"),
            "alert_count_7d": g.get("alert_count_7d"),
            "synthetic_count_7d": g.get("synthetic_count_7d"),
            "synthetic_ratio_7d": g.get("synthetic_ratio_7d"),
            "last_alert_age_hours": round(float(g.get("last_alert_age_hours", 0)), 2),
            "confidence_avg": g.get("confidence_avg"),
        } for g in gaps[:limit]]
        return _build_cors_response(jsonify({"items": data, "count": len(data)}))
    except Exception as e:
        logger.error(f"/api/monitoring/dashboard/top_gaps error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Top gaps unavailable"}), 500))


@app.route("/api/monitoring/dashboard/top_covered", methods=["GET", "OPTIONS"])  # compact list
def monitoring_dashboard_top_covered():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    try:
        from coverage_monitor import get_coverage_monitor
        mon = get_coverage_monitor()
        limit = max(1, min(int(request.args.get("limit", 5)), 50))
        items = mon.get_covered_locations()[:limit]
        return _build_cors_response(jsonify({"items": items, "count": len(items)}))
    except Exception as e:
        logger.error(f"/api/monitoring/dashboard/top_covered error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Top covered unavailable"}), 500))

# ---------- Monitoring Trends Endpoints ----------
@app.route("/api/monitoring/trends", methods=["GET"])
def monitoring_trends():
    try:
        limit = max(1, min(int(request.args.get("limit", 168)), 2000))
        from metrics_trends import fetch_trends
        rows = fetch_trends(limit=limit)
        return _build_cors_response(jsonify({"items": rows, "count": len(rows)}))
    except Exception as e:
        logger.error(f"/api/monitoring/trends error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Trends unavailable"}), 500))

# ---------- GDELT Ingestion Admin Endpoint ----------
@app.route("/admin/gdelt/ingest", methods=["POST", "OPTIONS"])
def admin_gdelt_ingest():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    # Simple API key gate (reuse existing X-API-Key scheme if present)
    api_key = request.headers.get("X-API-Key")
    expected = os.getenv("ADMIN_API_KEY") or os.getenv("API_KEY")
    if expected and api_key != expected:
        return _build_cors_response(make_response(jsonify({"error": "Unauthorized"}), 401))
    try:
        from gdelt_ingest import manual_trigger
        result = manual_trigger()
        return _build_cors_response(jsonify({"ok": True, **result}))
    except Exception as e:
        logger.error(f"/admin/gdelt/ingest error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "GDELT ingest failed"}), 500))

@app.route("/admin/gdelt/enrich", methods=["POST", "OPTIONS"])
def admin_gdelt_enrich():
    """Process unprocessed GDELT events into alerts"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    api_key = request.headers.get("X-API-Key")
    expected = os.getenv("ADMIN_API_KEY") or os.getenv("API_KEY")
    if expected and api_key != expected:
        return _build_cors_response(make_response(jsonify({"error": "Unauthorized"}), 401))
    
    try:
        from gdelt_enrichment_worker import process_batch, get_conn
        
        batch_size = int(request.args.get("batch_size", 1000))
        conn = get_conn()
        processed = process_batch(conn, batch_size)
        conn.close()
        
        return _build_cors_response(jsonify({
            "ok": True,
            "processed": processed,
            "batch_size": batch_size
        }))
    except Exception as e:
        logger.error(f"/admin/gdelt/enrich error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/gdelt/filter-stats", methods=["GET", "OPTIONS"])
def admin_gdelt_filter_stats():
    """Get current GDELT filter configuration and metrics"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    api_key = request.headers.get("X-API-Key")
    expected = os.getenv("ADMIN_API_KEY") or os.getenv("API_KEY")
    if expected and api_key != expected:
        return _build_cors_response(make_response(jsonify({"error": "Unauthorized"}), 401))
    
    try:
        from gdelt_filters import get_filter_stats
        from gdelt_ingest import get_ingest_metrics
        
        filter_config = get_filter_stats()
        ingest_metrics = get_ingest_metrics()
        
        # Check if filtering is enabled
        filters_enabled = os.getenv("GDELT_ENABLE_FILTERS", "false").lower() in ("true", "1", "yes")
        
        return _build_cors_response(jsonify({
            "ok": True,
            "filters_enabled": filters_enabled,
            "filter_config": filter_config,
            "ingest_metrics": ingest_metrics,
            "env_vars": {
                "GDELT_ENABLE_FILTERS": os.getenv("GDELT_ENABLE_FILTERS", "false"),
                "GDELT_MIN_GOLDSTEIN": os.getenv("GDELT_MIN_GOLDSTEIN", "-5.0"),
                "GDELT_MIN_MENTIONS": os.getenv("GDELT_MIN_MENTIONS", "3"),
                "GDELT_MIN_TONE": os.getenv("GDELT_MIN_TONE", "-5.0"),
                "GDELT_MAX_AGE_HOURS": os.getenv("GDELT_MAX_AGE_HOURS", "72"),
                "GDELT_REQUIRE_SOURCE_URL": os.getenv("GDELT_REQUIRE_SOURCE_URL", "false"),
                "GDELT_REQUIRE_PRECISE_COORDS": os.getenv("GDELT_REQUIRE_PRECISE_COORDS", "false")
            }
        }))
    except Exception as e:
        logger.error(f"/admin/gdelt/filter-stats error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))
        
        total_processed = 0
        batches = 0
        
        while batches < 100:  # Max 100 batches per request (100k events)
            processed = process_batch(conn, min(batch_size, 1000))
            total_processed += processed
            batches += 1
            
            if processed == 0:
                break
        
        conn.close()
        
        return _build_cors_response(jsonify({
            "ok": True,
            "processed": total_processed,
            "batches": batches,
            "message": f"Enriched {total_processed} GDELT events into alerts"
        }))
        
    except Exception as e:
        logger.error(f"/admin/gdelt/enrich error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/coordinates/cleanup", methods=["POST", "OPTIONS"])
def cleanup_corrupted_coordinates():
    """Clean up corrupted coordinates where longitude/latitude are outside valid ranges"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from db_utils import _get_db_connection
        
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            # Check corrupted data first
            cur.execute("""
                SELECT COUNT(*) FROM alerts 
                WHERE longitude IS NOT NULL 
                AND (longitude < -180 OR longitude > 180 OR latitude < -90 OR latitude > 90)
            """)
            corrupted_alerts = cur.fetchone()[0]
            
            cur.execute("""
                SELECT COUNT(*) FROM raw_alerts 
                WHERE longitude IS NOT NULL 
                AND (longitude < -180 OR longitude > 180 OR latitude < -90 OR latitude > 90)
            """)
            corrupted_raw = cur.fetchone()[0]
            
            logger.info(f"Found {corrupted_alerts} corrupted records in alerts table")
            logger.info(f"Found {corrupted_raw} corrupted records in raw_alerts table")
            
            # Clean alerts table
            if corrupted_alerts > 0:
                cur.execute("""
                    UPDATE alerts 
                    SET latitude = NULL, longitude = NULL 
                    WHERE longitude < -180 OR longitude > 180 OR latitude < -90 OR latitude > 90
                """)
                logger.info(f"Cleaned {corrupted_alerts} records in alerts")
            
            # Clean raw_alerts table
            if corrupted_raw > 0:
                cur.execute("""
                    UPDATE raw_alerts
                    SET latitude = NULL, longitude = NULL  
                    WHERE longitude < -180 OR longitude > 180 OR latitude < -90 OR latitude > 90
                """)
                logger.info(f"Cleaned {corrupted_raw} records in raw_alerts")
            
            conn.commit()
            
            # Verify cleanup
            cur.execute("""
                SELECT COUNT(*) FROM alerts 
                WHERE longitude IS NOT NULL 
                AND (longitude < -180 OR longitude > 180 OR latitude < -90 OR latitude > 90)
            """)
            remaining_alerts = cur.fetchone()[0]
            
            cur.execute("""
                SELECT COUNT(*) FROM raw_alerts 
                WHERE longitude IS NOT NULL 
                AND (longitude < -180 OR longitude > 180 OR latitude < -90 OR latitude > 90)
            """)
            remaining_raw = cur.fetchone()[0]
            
            # Count valid coordinates
            cur.execute("SELECT COUNT(*) FROM alerts WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
            valid_alerts = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM raw_alerts WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
            valid_raw = cur.fetchone()[0]
            
            cur.close()
        
        return _build_cors_response(jsonify({
            "ok": True,
            "cleaned": {
                "alerts": corrupted_alerts,
                "raw_alerts": corrupted_raw
            },
            "remaining_corrupted": {
                "alerts": remaining_alerts,
                "raw_alerts": remaining_raw
            },
            "valid_coordinates": {
                "alerts": valid_alerts,
                "raw_alerts": valid_raw
            },
            "message": f"Cleaned {corrupted_alerts + corrupted_raw} corrupted coordinate records"
        }))
        
    except Exception as e:
        logger.error(f"/admin/coordinates/cleanup error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/coordinates/fix-simple", methods=["POST", "OPTIONS"])
def fix_coordinates_simple():
    """Emergency fix: Geocode using country centroids (no API quota)"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from db_utils import _get_db_connection
        
        # Country centroids (major countries only, enough for GDELT)
        CENTROIDS = {
            'US': (39.8, -98.6), 'USA': (39.8, -98.6),
            'UK': (55.4, -3.4), 'GB': (55.4, -3.4),
            'FR': (46.2, 2.2), 'DE': (51.2, 10.5),
            'CN': (35.9, 104.2), 'IN': (20.6, 78.9),
            'BR': (-14.2, -51.9), 'RU': (61.5, 105.3),
            'JP': (36.2, 138.3), 'IT': (41.9, 12.6),
            'ES': (40.5, -3.7), 'CA': (56.1, -106.3),
            'AU': (-25.3, 133.8), 'MX': (23.6, -102.6),
            'KR': (36.0, 127.8), 'ID': (-0.8, 113.9),
            'TR': (39.0, 35.2), 'SA': (23.9, 45.1),
            'AR': (-38.4, -63.6), 'ZA': (-30.6, 22.9),
            'EG': (26.8, 30.8), 'PL': (51.9, 19.1),
            'UA': (48.4, 31.2), 'PK': (30.4, 69.3),
            'NG': (9.1, 8.7), 'BD': (23.7, 90.4),
            'IL': (31.0, 34.9), 'IQ': (33.2, 43.7),
            'SY': (34.8, 39.0), 'YE': (15.6, 48.5),
            'AF': (33.9, 67.7), 'IR': (32.4, 53.7),
            # Additional countries
            'NL': (52.1, 5.3), 'BE': (50.5, 4.5),
            'CH': (46.8, 8.2), 'AT': (47.5, 14.6),
            'SE': (60.1, 18.6), 'NO': (60.5, 8.5),
            'FI': (61.9, 25.7), 'DK': (56.3, 9.5),
            'GR': (39.1, 21.8), 'PT': (39.4, -8.2),
            'RO': (46.0, 25.0), 'HU': (47.2, 19.5),
            'CZ': (49.8, 15.5), 'BG': (42.7, 25.5),
            'RS': (44.0, 21.0), 'HR': (45.1, 15.2),
            'TH': (15.9, 100.9), 'VN': (14.1, 108.3),
            'MY': (4.2, 101.9), 'SG': (1.4, 103.8),
            'PH': (12.9, 121.8), 'MM': (22.0, 96.5),
            'CL': (-35.7, -71.5), 'CO': (4.6, -74.1),
            'PE': (-9.2, -75.0), 'VE': (6.4, -66.6),
            'KE': (-0.0, 37.9), 'TZ': (-6.4, 34.9),
            'UG': (1.4, 32.3), 'ET': (9.1, 40.5),
            'MA': (31.8, -7.1), 'DZ': (28.0, 1.7),
            'SD': (12.9, 30.2), 'LY': (26.3, 17.2),
        }
        
        batch_size = int(request.args.get("batch_size", 100))
        source_filter = request.args.get("source", "gdelt")
        
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get alerts needing geocoding
            cur.execute("""
                SELECT id, uuid, country, source
                FROM alerts
                WHERE (longitude IS NULL OR longitude = 0.0)
                  AND country IS NOT NULL
                  AND source = %s
                LIMIT %s
            """, (source_filter, batch_size))
            
            alerts = cur.fetchall()
            
            if not alerts:
                return _build_cors_response(jsonify({
                    "ok": True,
                    "geocoded": 0,
                    "message": "No alerts need geocoding"
                }))
            
            geocoded = 0
            failed = 0
            
            for alert_id, uuid, country, source in alerts:
                country_code = country.strip().upper() if country else None
                
                if country_code and country_code in CENTROIDS:
                    lat, lon = CENTROIDS[country_code]
                    cur.execute("""
                        UPDATE alerts
                        SET latitude = %s, longitude = %s
                        WHERE id = %s
                    """, (lat, lon, alert_id))
                    geocoded += 1
                else:
                    failed += 1
                    logger.warning(f"No centroid for country: {country}")
            
            conn.commit()
            cur.close()
        
        return _build_cors_response(jsonify({
            "ok": True,
            "geocoded": geocoded,
            "failed": failed,
            "total": len(alerts),
            "message": f"Geocoded {geocoded} using country centroids"
        }))
        
    except Exception as e:
        logger.error(f"/admin/coordinates/fix-simple error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/alerts/geocode-backfill", methods=["POST", "OPTIONS"])
def geocode_backfill():
    """Backfill geocoding for alerts with NULL coordinates that have city/country"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from db_utils import _get_db_connection
        from geocoding_service import geocode
        
        batch_size = int(request.args.get("batch_size", 100))
        
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get alerts with NULL coords but have city/country
            cur.execute("""
                SELECT id, uuid, city, country
                FROM alerts
                WHERE longitude IS NULL 
                  AND city IS NOT NULL 
                  AND country IS NOT NULL
                  AND source != 'gdelt'
                LIMIT %s
            """, (batch_size,))
            
            alerts_to_geocode = cur.fetchall()
            
            if not alerts_to_geocode:
                return _build_cors_response(jsonify({
                    "ok": True,
                    "geocoded": 0,
                    "message": "No alerts need geocoding"
                }))
            
            geocoded_count = 0
            failed_count = 0
            
            for alert_id, uuid, city, country in alerts_to_geocode:
                try:
                    # Geocode the city/country
                    location_str = f"{city}, {country}" if city else country
                    geo_result = geocode(location_str)
                    
                    if geo_result and geo_result.get('lat') and geo_result.get('lon'):
                        # Update alert with coordinates
                        cur.execute("""
                            UPDATE alerts
                            SET latitude = %s, longitude = %s
                            WHERE id = %s
                        """, (geo_result['lat'], geo_result['lon'], alert_id))
                        geocoded_count += 1
                        logger.info(f"Geocoded {uuid}: {city}, {country} → ({geo_result['lon']:.4f}, {geo_result['lat']:.4f})")
                    else:
                        failed_count += 1
                        logger.warning(f"Geocoding failed for {uuid}: {city}, {country}")
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error geocoding alert {uuid}: {e}")
            
            conn.commit()
            cur.close()
        
        return _build_cors_response(jsonify({
            "ok": True,
            "geocoded": geocoded_count,
            "failed": failed_count,
            "total_processed": len(alerts_to_geocode),
            "message": f"Geocoded {geocoded_count} alerts, {failed_count} failed"
        }))
        
    except Exception as e:
        logger.error(f"/admin/alerts/geocode-backfill error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/alerts/sources", methods=["GET", "OPTIONS"])
def check_alert_sources():
    """Check alert counts and coordinate status by source"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from db_utils import _get_db_connection
        
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            # Count alerts by source with coordinate stats
            cur.execute("""
                SELECT source, COUNT(*) as total,
                       SUM(CASE WHEN longitude = 0.0 THEN 1 ELSE 0 END) as lon_zero,
                       SUM(CASE WHEN longitude IS NULL THEN 1 ELSE 0 END) as lon_null,
                       SUM(CASE WHEN longitude != 0.0 AND longitude IS NOT NULL THEN 1 ELSE 0 END) as lon_valid
                FROM alerts
                GROUP BY source
                ORDER BY total DESC
            """)
            
            sources = []
            for row in cur.fetchall():
                sources.append({
                    'source': row[0],
                    'total': row[1],
                    'lon_zero': row[2],
                    'lon_null': row[3],
                    'lon_valid': row[4]
                })
            
            # Get sample RSS alerts
            cur.execute("""
                SELECT uuid, title, country, city, latitude, longitude
                FROM alerts
                WHERE source = 'rss'
                LIMIT 3
            """)
            rss_samples = []
            for row in cur.fetchall():
                rss_samples.append({
                    'uuid': row[0],
                    'title': row[1],
                    'country': row[2],
                    'city': row[3],
                    'coords': {'lat': row[4], 'lon': row[5]}
                })
            
            cur.close()
        
        return _build_cors_response(jsonify({
            "ok": True,
            "sources": sources,
            "rss_samples": rss_samples
        }))
        
    except Exception as e:
        logger.error(f"/admin/alerts/sources error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/geocoding/status", methods=["GET", "OPTIONS"])
def geocoding_status():
    """Check geocoding coverage and backlog status"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from geocoding_monitor import get_geocoding_status
        from db_utils import _get_db_connection
        
        with _get_db_connection() as conn:
            status = get_geocoding_status(conn)
        
        return _build_cors_response(jsonify({
            "ok": True,
            **status
        }))
        
    except Exception as e:
        logger.error(f"/admin/geocoding/status error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/geocoding/notify", methods=["POST", "OPTIONS"])
def geocoding_notify():
    """Manually trigger geocoding backlog notification check"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from geocoding_monitor import check_and_notify
        
        result = check_and_notify()
        
        return _build_cors_response(jsonify({
            "ok": True,
            **result
        }))
        
    except Exception as e:
        logger.error(f"/admin/geocoding/notify error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/geocoding/queue-status", methods=["GET", "OPTIONS"])
def geocoding_queue_status():
    """Show geocoding queue depth and quota status (Redis/RQ)."""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))

    try:
        from geocoding_service import get_quota_status, _get_redis
        from rq import Queue
        from rq.registry import StartedJobRegistry, FailedJobRegistry, ScheduledJobRegistry, DeferredJobRegistry

        r = _get_redis()
        if not r:
            return _build_cors_response(make_response(jsonify({
                "ok": False,
                "error": "Redis not configured",
            }), 503))

        q = Queue('geocoding', connection=r)
        started_reg = StartedJobRegistry('geocoding', connection=r)
        failed_reg = FailedJobRegistry('geocoding', connection=r)
        scheduled_reg = ScheduledJobRegistry('geocoding', connection=r)
        deferred_reg = DeferredJobRegistry('geocoding', connection=r)

        try:
            inflight = int(r.scard('geocoding:inflight'))
        except Exception:
            inflight = None

        quota = get_quota_status()

        payload = {
            "ok": True,
            "queue": {
                "queued": q.count,
                "started": len(started_reg.get_job_ids()),
                "scheduled": len(scheduled_reg.get_job_ids()),
                "failed": len(failed_reg.get_job_ids()),
                "deferred": len(deferred_reg.get_job_ids()),
                "inflight_dedup": inflight,
            },
            "quota": quota
        }

        return _build_cors_response(jsonify(payload))
    except Exception as e:
        logger.error(f"/admin/geocoding/queue-status error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/geocoding/dashboard", methods=["GET", "OPTIONS"])
def geocoding_dashboard():
    """Compact dashboard combining coverage/backlog, queue depth, and quota status."""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))

    try:
        # Coverage/backlog
        from geocoding_monitor import get_geocoding_status
        from db_utils import _get_db_connection
        with _get_db_connection() as conn:
            coverage = get_geocoding_status(conn)

        # Queue + quota
        from geocoding_service import get_quota_status, _get_redis
        from rq import Queue
        from rq.registry import StartedJobRegistry, FailedJobRegistry, ScheduledJobRegistry, DeferredJobRegistry

        r = _get_redis()
        queue_payload = None
        if r:
            q = Queue('geocoding', connection=r)
            started_reg = StartedJobRegistry('geocoding', connection=r)
            failed_reg = FailedJobRegistry('geocoding', connection=r)
            scheduled_reg = ScheduledJobRegistry('geocoding', connection=r)
            deferred_reg = DeferredJobRegistry('geocoding', connection=r)
            try:
                inflight = int(r.scard('geocoding:inflight'))
            except Exception:
                inflight = None
            queue_payload = {
                "queued": q.count,
                "started": len(started_reg.get_job_ids()),
                "scheduled": len(scheduled_reg.get_job_ids()),
                "failed": len(failed_reg.get_job_ids()),
                "deferred": len(deferred_reg.get_job_ids()),
                "inflight_dedup": inflight,
            }

        quota = get_quota_status()

        return _build_cors_response(jsonify({
            "ok": True,
            "coverage": coverage,
            "queue": queue_payload or {"error": "Redis not configured"},
            "quota": quota
        }))
    except Exception as e:
        logger.error(f"/admin/geocoding/dashboard error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/geocoding/dashboard/view", methods=["GET"]) 
def geocoding_dashboard_view():
    """Server-rendered HTML view of geocoding coverage, queue, and quota."""
    try:
        # Coverage/backlog
        from geocoding_monitor import get_geocoding_status
        from db_utils import _get_db_connection
        with _get_db_connection() as conn:
            coverage = get_geocoding_status(conn)

        # Queue + quota
        from geocoding_service import get_quota_status, _get_redis
        from rq import Queue
        from rq.registry import StartedJobRegistry, FailedJobRegistry, ScheduledJobRegistry, DeferredJobRegistry

        r = _get_redis()
        queue_payload = None
        if r:
            q = Queue('geocoding', connection=r)
            started_reg = StartedJobRegistry('geocoding', connection=r)
            failed_reg = FailedJobRegistry('geocoding', connection=r)
            scheduled_reg = ScheduledJobRegistry('geocoding', connection=r)
            deferred_reg = DeferredJobRegistry('geocoding', connection=r)
            try:
                inflight = int(r.scard('geocoding:inflight'))
            except Exception:
                inflight = None
            queue_payload = {
                "queued": q.count,
                "started": len(started_reg.get_job_ids()),
                "scheduled": len(scheduled_reg.get_job_ids()),
                "failed": len(failed_reg.get_job_ids()),
                "deferred": len(deferred_reg.get_job_ids()),
                "inflight_dedup": inflight,
            }

        quota = get_quota_status()

        return render_template(
            "admin_geocoding_dashboard.html",
            coverage=coverage,
            queue=queue_payload,
            quota=quota,
        )
    except Exception as e:
        logger.error(f"/admin/geocoding/dashboard/view error: {e}")
        return make_response(f"Dashboard error: {e}", 500)

@app.route("/admin/gdelt/reprocess", methods=["POST", "OPTIONS"])
def gdelt_reprocess_coords():
    """Reprocess GDELT events with invalid coordinates (lon=0) to geocode them properly"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from db_utils import _get_db_connection
        
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            # First check how many events we have with lon=0
            cur.execute("""
                SELECT COUNT(*) FROM gdelt_events
                WHERE action_long = 0.0 
                  AND quad_class IN (3, 4)
            """)
            total_with_zero = cur.fetchone()[0]
            
            # Mark GDELT events with lon=0 as unprocessed so enrichment worker will reprocess them
            cur.execute("""
                UPDATE gdelt_events
                SET processed = false
                WHERE action_long = 0.0 
                  AND quad_class IN (3, 4)
            """)
            marked_count = cur.rowcount
            
            # Delete existing raw_alerts/alerts with lon=0 so they can be regenerated
            cur.execute("""
                DELETE FROM alerts
                WHERE longitude = 0.0 AND uuid LIKE 'gdelt-%'
            """)
            deleted_alerts = cur.rowcount
            
            cur.execute("""
                DELETE FROM raw_alerts
                WHERE longitude = 0.0 AND uuid LIKE 'gdelt-%'
            """)
            deleted_raw = cur.rowcount
            
            conn.commit()
            
            # Check unprocessed count after update
            cur.execute("""
                SELECT COUNT(*) FROM gdelt_events
                WHERE processed = false
                  AND quad_class IN (3, 4)
            """)
            unprocessed_count = cur.fetchone()[0]
            
            logger.info(f"Total GDELT events with lon=0: {total_with_zero}")
            logger.info(f"Marked {marked_count} GDELT events for reprocessing")
            logger.info(f"Unprocessed events after update: {unprocessed_count}")
            logger.info(f"Deleted {deleted_alerts} alerts and {deleted_raw} raw_alerts with lon=0")
        
        return _build_cors_response(jsonify({
            "ok": True,
            "total_with_zero_lon": total_with_zero,
            "marked_for_reprocessing": marked_count,
            "unprocessed_count": unprocessed_count,
            "deleted_alerts": deleted_alerts,
            "deleted_raw_alerts": deleted_raw,
            "message": f"Marked {marked_count} events for reprocessing. {unprocessed_count} events ready. Run /admin/gdelt/enrich to geocode them."
        }))
        
    except Exception as e:
        logger.error(f"/admin/gdelt/reprocess error: {e}")
        return _build_cors_response(make_response(jsonify({"error": str(e)}), 500))

@app.route("/admin/gdelt/health", methods=["GET", "OPTIONS"])
def gdelt_health():
    """Check GDELT ingestion status"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from db_utils import _get_db_connection
        
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get last successful ingest file
            cur.execute(
                "SELECT value FROM gdelt_state WHERE key = 'last_export_file'"
            )
            last_file = cur.fetchone()
            
            # Get event count (last 24h)
            cur.execute(
                "SELECT COUNT(*) FROM gdelt_events WHERE sql_date >= %s",
                ((datetime.utcnow() - timedelta(hours=24)).strftime('%Y%m%d'),)
            )
            count_24h = cur.fetchone()[0]
            
            # Get last metric with details
            cur.execute(
                "SELECT timestamp, events_inserted, ingestion_duration_sec FROM gdelt_metrics ORDER BY timestamp DESC LIMIT 1"
            )
            last_metric = cur.fetchone()
        
        # Check if polling is stale (no ingest in 30min)
        is_stale = False
        if last_metric:
            last_time = last_metric[0]
            from datetime import timezone
            now = datetime.now(timezone.utc)
            is_stale = (now - last_time).total_seconds() > 1800  # 30 min
        
        return _build_cors_response(jsonify({
            'status': 'stale' if is_stale else 'healthy',
            'last_file': last_file[0] if last_file else None,
            'events_24h': count_24h,
            'last_ingest': {
                'timestamp': last_metric[0].isoformat() if last_metric else None,
                'events_inserted': last_metric[1] if last_metric else 0,
                'duration_sec': float(last_metric[2]) if last_metric else 0
            },
            'polling_enabled': os.getenv('GDELT_ENABLED') == 'true'
        }))
    except Exception as e:
        logger.error(f"/admin/gdelt/health error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Health check failed"}), 500))

# ---------- GDELT Query API Endpoints ----------
@app.route("/api/threats/location", methods=["POST", "OPTIONS"])
def threats_near_location():
    """Get GDELT threats near coordinates"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        data = request.json
        
        from gdelt_query import GDELTQuery
        threats = GDELTQuery.get_threats_near_location(
            lat=data['lat'],
            lon=data['lon'],
            radius_km=data.get('radius_km', 50),
            days=data.get('days', 7)
        )
        
        return _build_cors_response(jsonify({
            'source': 'GDELT',
            'count': len(threats),
            'threats': threats
        }))
    except Exception as e:
        logger.error(f"/api/threats/location error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

@app.route("/api/threats/country/<country_code>", methods=["GET", "OPTIONS"])
def country_threat_summary(country_code):
    """Get GDELT threat summary for country"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        days = request.args.get('days', 30, type=int)
        
        from gdelt_query import GDELTQuery
        summary = GDELTQuery.get_country_summary(country_code.upper(), days)
        
        if not summary:
            return _build_cors_response(jsonify({'error': 'No threat data for country'}), 404)
        
        return _build_cors_response(jsonify(summary))
    except Exception as e:
        logger.error(f"/api/threats/country/{country_code} error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

@app.route("/api/threats/trending", methods=["GET", "OPTIONS"])
def trending_threats():
    """Get most-covered GDELT threats"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        days = request.args.get('days', 7, type=int)
        
        from gdelt_query import GDELTQuery
        threats = GDELTQuery.get_trending_threats(days)
        
        return _build_cors_response(jsonify({
            'source': 'GDELT',
            'count': len(threats),
            'threats': threats
        }))
    except Exception as e:
        logger.error(f"/api/threats/trending error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

@app.route("/api/threats/assess", methods=["POST", "OPTIONS"])
def assess_threats():
    """Unified threat assessment combining all intelligence sources"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        data = request.json
        
        lat = data.get('lat')
        lon = data.get('lon')
        country_code = data.get('country_code')
        radius_km = data.get('radius_km', 100)
        days = data.get('days', 14)
        
        if lat is None or lon is None:
            return _build_cors_response(jsonify({'error': 'lat and lon are required'}), 400)
        
        from threat_fusion import ThreatFusion
        assessment = ThreatFusion.assess_location(
            lat=float(lat),
            lon=float(lon),
            country_code=country_code,
            radius_km=int(radius_km),
            days=int(days)
        )
        
        return _build_cors_response(jsonify(assessment))
    except Exception as e:
        logger.error(f"/api/threats/assess error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Assessment failed"}), 500))


def _generate_llm_travel_advisory(assessment: dict, destination: str | None = None) -> str:
    """Generate a tactical travel risk advisory using the LLM router.
    Falls back to a concise, local summary if LLMs are unavailable.
    """
    try:
        # Build a context-rich prompt from assessment
        loc = assessment.get("location", {})
        cs = assessment.get("country_summary") or {}
        categories = assessment.get("threat_categories") or {}
        top_threats = assessment.get("top_threats") or []

        summary_lines = []
        summary_lines.append(f"DESTINATION: {destination or 'Unknown'}")
        summary_lines.append(f"COORDINATES: {loc.get('lat')}, {loc.get('lon')}")
        summary_lines.append(f"ASSESSMENT PERIOD: Last {assessment.get('period_days', 14)} days")
        summary_lines.append("")
        summary_lines.append(f"OVERALL RISK LEVEL: {assessment.get('risk_level', 'UNKNOWN')}")
        summary_lines.append("")
        summary_lines.append("INTELLIGENCE SUMMARY:")
        summary_lines.append(f"- Total threats identified: {assessment.get('total_threats', 0)}")
        src = assessment.get('sources', {})
        summary_lines.append(f"- GDELT events: {src.get('gdelt_events', 0)}")
        summary_lines.append(f"- RSS alerts: {src.get('rss_alerts', 0)}")
        summary_lines.append(f"- ACLED conflicts: {src.get('acled_events', 0)}")
        summary_lines.append("")

        if cs:
            summary_lines.append(f"COUNTRY CONTEXT ({cs.get('country', loc.get('country', 'Unknown'))}):")
            summary_lines.append(f"- Total events (30 days): {cs.get('total_events', 0)}")
            if cs.get('avg_severity') is not None:
                try:
                    summary_lines.append(f"- Average severity: {float(cs.get('avg_severity')):.1f}/10")
                except Exception:
                    summary_lines.append(f"- Average severity: {cs.get('avg_severity')}/10")
            if cs.get('worst_severity') is not None:
                try:
                    summary_lines.append(f"- Worst event severity: {float(cs.get('worst_severity')):.1f}/10")
                except Exception:
                    summary_lines.append(f"- Worst event severity: {cs.get('worst_severity')}/10")
            if cs.get('unique_actors') is not None:
                summary_lines.append(f"- Unique threat actors: {cs.get('unique_actors')}")
            summary_lines.append("")

        if categories:
            summary_lines.append("THREAT BREAKDOWN BY TYPE:")
            for category, items in categories.items():
                summary_lines.append(f"- {category.replace('_',' ').title()}: {len(items)} events")
            summary_lines.append("")

        if top_threats:
            summary_lines.append("TOP RECENT THREATS:")
            for i, t in enumerate(top_threats[:5], 1):
                actor1 = t.get('actor1', 'Unknown')
                actor2 = t.get('actor2', 'Unknown')
                country = t.get('country') or loc.get('country') or 'unknown location'
                try:
                    dist_km = float(t.get('distance_km', 0.0))
                except Exception:
                    dist_km = 0.0
                try:
                    sev = float(t.get('severity', 0.0))
                except Exception:
                    sev = 0.0
                srcs = t.get('source', 'Unknown')
                summary_lines.append(f"{i}. {actor1} vs {actor2} in {country} ({dist_km:.0f}km away, severity: {sev:.1f}/10)")
                summary_lines.append(f"   Sources: {srcs}")
            summary_lines.append("")

        summary_lines.append(
            "Generate a concise, operator-grade travel risk advisory with:\n\n"
            "1. THREAT LEVEL: One-line summary\n"
            "2. PRIMARY THREATS: Top 3 specific threats by likelihood/impact\n"
            "3. GEOGRAPHIC RISK ZONES: Areas to avoid (be specific)\n"
            "4. OPERATIONAL RECOMMENDATIONS:\n   - Pre-travel prep\n   - In-country security posture\n   - Emergency protocols\n"
            "5. TIMELINE CONSIDERATIONS: Events/dates that increase risk\n\n"
            "Keep it tactical, direct, and actionable. No fluff."
        )

        prompt = "\n".join(summary_lines)

        # Call LLM via router (advisor task type)
        try:
            from llm_router import route_llm
            messages = [
                {"role": "system", "content": "You are a professional security analyst. Provide tactical, actionable travel risk advisories."},
                {"role": "user", "content": prompt},
            ]
            advisory, model_name = route_llm(messages, temperature=0.3, task_type="advisor")
            if advisory and advisory.strip():
                return advisory.strip()
        except Exception as e:
            logger.warning(f"/api/travel-risk/assess LLM routing failed: {e}")

        # Fallback: return compact local summary if LLM unavailable
        fallback = [
            f"Threat Level: {assessment.get('risk_level', 'UNKNOWN')}",
            f"Threats nearby: {assessment.get('total_threats', 0)} in last {assessment.get('period_days', 14)} days",
        ]
        if assessment.get('recommendations'):
            recs = assessment['recommendations'][:3]
            fallback.append("Top recommendations:")
            for r in recs:
                fallback.append(f"- {r}")
        return "\n".join(fallback)
    except Exception as e:
        logger.error(f"/api/travel-risk/assess advisory generation error: {e}")
        return "Advisory generation failed. Review raw threat data."


def _assessment_to_alert_for_advisor(assessment: dict, destination: str | None = None) -> dict:
    """Convert ThreatFusion assessment into an advisor-friendly 'alert' dict.
    This produces a single synthetic alert summarizing the local threat picture.
    """
    loc = assessment.get("location", {})
    categories = assessment.get("threat_categories") or {}
    top_threats = assessment.get("top_threats") or []

    # Derive a concise title and summary
    risk = assessment.get("risk_level", "UNKNOWN")
    title = f"{destination or loc.get('country') or 'Destination'} — {risk} risk"

    # Build a terse summary string
    src = assessment.get("sources", {})
    parts = [
        f"{assessment.get('total_threats', 0)} local threats in last {assessment.get('period_days', 14)}d",
        f"GDELT:{src.get('gdelt_events',0)} RSS:{src.get('rss_alerts',0)} ACLED:{src.get('acled_events',0)}",
    ]
    if categories:
        cat_counts = ", ".join(f"{k}:{len(v)}" for k, v in categories.items() if v)
        if cat_counts:
            parts.append(cat_counts)
    summary = " | ".join(parts)

    # Choose primary category from categories with max events
    primary_category = None
    if categories:
        primary_category = max(categories.items(), key=lambda kv: len(kv[1]) if isinstance(kv[1], list) else 0)[0]

    # Build sources list from top_threats
    src_list = []
    seen = set()
    for t in top_threats[:10]:
        s = t.get('source')
        if not s:
            continue
        # Split combined labels like "GDELT, RSS"
        names = [x.strip() for x in str(s).split(',') if x.strip()]
        for name in names:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            src_list.append({"name": name})

    # Score: scale from risk level
    score_map = {"LOW": 0.25, "MODERATE": 0.5, "HIGH": 0.75, "SEVERE": 0.9}
    score = score_map.get(str(risk).upper(), 0.5)

    # Confidence: increase if multi-source verification present
    conf = 0.5
    try:
        ver = int(assessment.get('verified_by_multiple_sources') or 0)
        if ver >= 3:
            conf = 0.8
        elif ver >= 1:
            conf = 0.65
    except Exception:
        pass

    # Compose alert dict
    alert = {
        "title": title,
        "summary": summary,
        "city": None,  # unknown from assessment
        "region": None,
        "country": loc.get("country"),
        "latitude": loc.get("lat"),
        "longitude": loc.get("lon"),
        "category": primary_category or "travel_mobility",
        "subcategory": "Local risk picture",
        "label": risk,
        "score": score,
        "confidence": conf,
        "domains": [],  # allow advisor to infer if absent
        "sources": src_list,
        # Minimal trend payload
        "incident_count_30d": assessment.get("total_threats", 0),
        "recent_count_7d": None,
        "baseline_avg_7d": None,
        "baseline_ratio": 1.0,
        "trend_direction": "stable",
        "anomaly_flag": False,
        "future_risk_probability": None,
        # Early warnings / playbooks left empty; advisor fills defaults
    }
    return alert


@app.route('/api/travel-risk/assess', methods=['POST', 'OPTIONS'])
@limiter.limit(TRAVEL_RISK_RATE) if limiter else lambda f: f
def travel_risk_assessment():
    """Unified travel risk assessment plus LLM advisory for a destination."""
    if request.method == 'OPTIONS':
        return _build_cors_response(make_response("", 204))

    try:
        data = request.json or {}

        # Validate inputs
        if not ("lat" in data and "lon" in data):
            return _build_cors_response(jsonify({'error': 'lat and lon required'}), 400)

        destination = data.get('destination')
        lat = float(data['lat'])
        lon = float(data['lon'])
        country_code = data.get('country_code')
        
        # Sanitize bounds for radius and days
        radius_km = int(data.get('radius_km', 100))
        radius_km = max(1, min(radius_km, 500))  # Clamp between 1-500 km
        
        days = int(data.get('days', 14))
        days = max(1, min(days, 365))  # Clamp between 1-365 days
        
        output_format = str(data.get('format', 'structured')).lower()
        
        # Generate cache key
        cache_key = f"travel-risk:{lat:.4f}:{lon:.4f}:{country_code or 'none'}:{radius_km}:{days}:{output_format}"
        
        # Try cache (Redis first, then in-memory)
        cached_result = None
        if travel_risk_cache:
            try:
                import json
                cached_json = travel_risk_cache.get(cache_key)
                if cached_json:
                    cached_result = json.loads(cached_json)
                    logger.info("travel_risk_cache_hit", cache_key=cache_key)
            except Exception as e:
                logger.warning(f"Redis cache read failed: {e}")
        
        # In-memory fallback cache
        if not cached_result and cache_key in travel_risk_memory_cache:
            entry = travel_risk_memory_cache[cache_key]
            if time.time() - entry['timestamp'] < TRAVEL_RISK_CACHE_TTL:
                cached_result = entry['data']
                logger.info("travel_risk_cache_hit", cache_key=cache_key, source="memory")
            else:
                # Expired, remove
                del travel_risk_memory_cache[cache_key]
        
        if cached_result:
            return _build_cors_response(jsonify(cached_result))

        # Analytics logging for popular destinations
        user_email = None
        try:
            user_email = get_logged_in_email() if 'get_logged_in_email' in globals() else None
        except Exception:
            pass
        
        logger.info("travel_risk_query",
            extra={
                "lat": lat,
                "lon": lon,
                "country_code": country_code,
                "destination": destination,
                "radius_km": radius_km,
                "days": days,
                "format": output_format,
                "user_email": user_email,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # Run fusion analysis
        from threat_fusion import ThreatFusion
        assessment = ThreatFusion.assess_location(
            lat=lat,
            lon=lon,
            country_code=country_code,
            radius_km=radius_km,
            days=days,
        )

        # Generate advisory: structured (advisor.py) or concise (LLM router)
        advisory_text = ""
        if output_format == "structured":
            try:
                alert = _assessment_to_alert_for_advisor(assessment, destination)
                from advisor import render_advisory
                profile = {"location": destination} if destination else {}
                user_msg = destination or f"{lat},{lon}"
                advisory_text = render_advisory(alert, user_msg, profile)
            except Exception as e:
                logger.warning(f"/api/travel-risk/assess structured advisor failed, falling back: {e}")
                advisory_text = _generate_llm_travel_advisory(assessment, destination)
        else:
            advisory_text = _generate_llm_travel_advisory(assessment, destination)

        result = {
            'assessment': assessment,
            'advisory': advisory_text,
            'format': output_format,
        }
        
        # Store in cache
        if travel_risk_cache:
            try:
                import json
                travel_risk_cache.setex(cache_key, TRAVEL_RISK_CACHE_TTL, json.dumps(result))
                logger.info("travel_risk_cache_set", cache_key=cache_key, ttl=TRAVEL_RISK_CACHE_TTL)
            except Exception as e:
                logger.warning(f"Redis cache write failed: {e}")
        
        # In-memory cache
        travel_risk_memory_cache[cache_key] = {
            'data': result,
            'timestamp': time.time()
        }
        
        # Clean old in-memory entries (keep last 100)
        if len(travel_risk_memory_cache) > 100:
            oldest_keys = sorted(travel_risk_memory_cache.keys(), 
                               key=lambda k: travel_risk_memory_cache[k]['timestamp'])[:50]
            for k in oldest_keys:
                del travel_risk_memory_cache[k]
        
        return _build_cors_response(jsonify(result))
    except Exception as e:
        logger.error(f"/api/travel-risk/assess error: {e}")
        return _build_cors_response(make_response(jsonify({'error': 'Assessment or advisory failed'}), 500))

@app.route("/admin/monitoring/snapshot", methods=["POST"])  # admin-only manual snapshot
def monitoring_snapshot_admin():
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        if not expected_key or api_key != expected_key:
            return make_response(jsonify({"error": "Unauthorized - valid API key required"}), 401)
        from metrics_trends import snapshot_coverage_trends, ensure_trends_table
        ensure_trends_table()
        row = snapshot_coverage_trends()
        return jsonify({"ok": True, "snapshot": row})
    except Exception as e:
        logger.error(f"/admin/monitoring/snapshot error: {e}")
        return make_response(jsonify({"error": "Snapshot failed"}), 500)

# ---------- Admin: Trigger Real-Time Fallback (Phase 4) ----------
@app.route("/admin/fallback/trigger", methods=["POST"])
def trigger_realtime_fallback():
    """Manually trigger Phase 4 real-time fallback cycle (admin only).

    Header: X-API-Key: <ADMIN_API_KEY>
    Optional query/body fields may be added in future (e.g., country filter).
    """
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")

        if not expected_key or api_key != expected_key:
            # Do NOT echo CORS for admin; server-to-server only
            return make_response(jsonify({"error": "Unauthorized - valid API key required"}), 401)

        # Acting user context (for audit)
        acting_email = request.headers.get("X-Acting-Email", "unknown@system")
        acting_plan = request.headers.get("X-Acting-Plan", "UNKNOWN").upper()

        from real_time_fallback import perform_realtime_fallback
        # Filters via query or JSON body (country required, region optional)
        body = {}
        try:
            body = request.get_json(silent=True) or {}
        except Exception:
            body = {}
        country = (request.args.get("country") or body.get("country") or "").strip()
        region = (request.args.get("region") or body.get("region") or "").strip() or None

        # Input validation: country required
        if not country:
            return make_response(jsonify({"error": "country is required"}), 400)

        # Normalize inputs
        def _norm_country(c: str) -> str:
            try:
                import pycountry  # type: ignore
                # Try fuzzy search
                try:
                    res = pycountry.countries.search_fuzzy(c)
                    if res:
                        return res[0].name
                except Exception:
                    pass
            except Exception:
                pass
            return c.strip().title()

        def _norm_region(r: str) -> str:
            return (r or "").strip().title()

        country_n = _norm_country(country)
        region_n = _norm_region(region) if region else None

        # Rate limit: optional Redis-backed sliding window, fallback to in-memory bucket
        rl_key = f"{acting_email}:{country_n}:{region_n or 'ALL'}"
        now = time.time()
        window = float(os.getenv("ADMIN_FALLBACK_WINDOW_SEC", "60"))
        limit = int(os.getenv("ADMIN_FALLBACK_RPM", "10"))  # requests per window per key
        use_redis_rl = os.getenv("USE_REDIS_ADMIN_LIMITER", "false").lower() == "true"
        redis_client = None
        if use_redis_rl:
            try:
                import redis  # type: ignore
                if not hasattr(trigger_realtime_fallback, "_redis_admin_client"):
                    url = os.getenv("ADMIN_LIMITER_REDIS_URL") or os.getenv("REDIS_URL")
                    trigger_realtime_fallback._redis_admin_client = redis.from_url(url) if url else None  # type: ignore
                redis_client = getattr(trigger_realtime_fallback, "_redis_admin_client", None)
            except Exception as e:
                logger.warning(f"Admin redis limiter init failed: {e}")
                redis_client = None
        allowed = True
        retry_in = 0
        if redis_client:
            try:
                key = f"admin_rl:{rl_key}"
                pipe = redis_client.pipeline()
                cutoff = now - window
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zcard(key)
                current = pipe.execute()[1]
                if current >= limit:
                    allowed = False
                    # fetch oldest to compute retry_in
                    oldest = redis_client.zrange(key, 0, 0, withscores=True)
                    if oldest:
                        retry_in = int(window - (now - oldest[0][1]))
                else:
                    pipe = redis_client.pipeline()
                    pipe.zadd(key, {str(now): now})
                    pipe.expire(key, int(window))
                    pipe.execute()
            except Exception as e:
                logger.warning(f"Redis limiter error, falling back to memory: {e}")
                redis_client = None
        if not redis_client and allowed:
            if not hasattr(trigger_realtime_fallback, "_rate_buckets"):
                trigger_realtime_fallback._rate_buckets = {}
            buckets = trigger_realtime_fallback._rate_buckets  # type: ignore
            ts_list = [t for t in buckets.get(rl_key, []) if now - t < window]
            if len(ts_list) >= limit:
                allowed = False
                retry_in = int(window - (now - ts_list[0]))
            else:
                ts_list.append(now)
                buckets[rl_key] = ts_list
        if not allowed:
            return make_response(jsonify({"error": "rate_limited", "retry_in_sec": retry_in}), 429)

        corr_id = str(uuid.uuid4())
        t0 = time.time()
        attempts = perform_realtime_fallback(country=country_n, region=region_n)
        latency_ms = int((time.time() - t0) * 1000)

        # Audit log
        try:
            logger.info(
                "admin_fallback_trigger",
                extra={
                    "corr_id": corr_id,
                    "acting_email": acting_email,
                    "acting_plan": acting_plan,
                    "country": country_n,
                    "region": region_n,
                    "attempts": len(attempts),
                    "latency_ms": latency_ms,
                },
            )
        except Exception:
            pass

        # Do NOT apply CORS to admin endpoint responses
        return jsonify({
            "ok": True,
            "count": len(attempts),
            "attempts": attempts,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "correlation_id": corr_id,
            "latency_ms": latency_ms,
        })
    except Exception as e:
        logger.error(f"trigger_realtime_fallback error: {e}")
        return make_response(jsonify({"error": "Fallback trigger failed", "details": str(e)}), 500)


# ---------- Admin: Submit asynchronous fallback job ----------
@app.route("/admin/fallback/submit", methods=["POST"])
def submit_fallback_job_endpoint():
    """Queue a real-time fallback job and return job_id.

    Header: X-API-Key: <ADMIN_API_KEY>
    Body/Query: country (required), region (optional)
    """
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        if not expected_key or api_key != expected_key:
            return make_response(jsonify({"error": "Unauthorized - valid API key required"}), 401)
        if submit_fallback_job is None:
            return make_response(jsonify({"error": "Job queue unavailable"}), 503)
        body = {}
        try:
            body = request.get_json(silent=True) or {}
        except Exception:
            body = {}
        country = (request.args.get("country") or body.get("country") or "").strip()
        region = (request.args.get("region") or body.get("region") or "").strip() or None
        if not country:
            return make_response(jsonify({"error": "country is required"}), 400)
        acting_email = request.headers.get("X-Acting-Email", "unknown@system")
        acting_plan = request.headers.get("X-Acting-Plan", "UNKNOWN").upper()
        # Normalization (reuse logic from trigger endpoint)
        def _norm_country(c: str) -> str:
            try:
                import pycountry  # type: ignore
                try:
                    res = pycountry.countries.search_fuzzy(c)
                    if res:
                        return res[0].name
                except Exception:
                    pass
            except Exception:
                pass
            return c.strip().title()
        def _norm_region(r: str) -> str:
            return (r or "").strip().title()
        country_n = _norm_country(country)
        region_n = _norm_region(region) if region else None
        job = submit_fallback_job(country_n, region_n, acting_email, acting_plan)
        logger.info("admin_fallback_submit", extra={"job_id": job.get("job_id"), "country": country_n, "region": region_n, "acting_email": acting_email})
        return jsonify({
            "ok": True,
            "job_id": job.get("job_id"),
            "status": job.get("status"),
            "correlation_id": job.get("correlation_id"),
            "queue_enabled": bool(job_queue_enabled and job_queue_enabled()),
        })
    except Exception as e:
        logger.error(f"submit_fallback_job_endpoint error: {e}")
        return make_response(jsonify({"error": "Job submit failed", "details": str(e)}), 500)


# ---------- Admin: Fallback job status ----------
@app.route("/admin/fallback/status", methods=["GET"])
def fallback_job_status_endpoint():
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        if not expected_key or api_key != expected_key:
            return make_response(jsonify({"error": "Unauthorized - valid API key required"}), 401)
        if get_fallback_job_status is None:
            return make_response(jsonify({"error": "Job queue unavailable"}), 503)
        job_id = (request.args.get("job_id") or "").strip()
        if not job_id:
            return make_response(jsonify({"error": "job_id is required"}), 400)
        status = get_fallback_job_status(job_id)
        if not status:
            return make_response(jsonify({"error": "job_not_found"}), 404)
        return jsonify({"ok": True, "job": status})
    except Exception as e:
        logger.error(f"fallback_job_status_endpoint error: {e}")
        return make_response(jsonify({"error": "Status lookup failed", "details": str(e)}), 500)


# ---------- Admin: List recent fallback jobs ----------
@app.route("/admin/fallback/jobs", methods=["GET"])
def list_fallback_jobs_endpoint():
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        if not expected_key or api_key != expected_key:
            return make_response(jsonify({"error": "Unauthorized - valid API key required"}), 401)
        if list_fallback_jobs is None:
            return make_response(jsonify({"error": "Job queue unavailable"}), 503)
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
        jobs = list_fallback_jobs(limit=limit)
        return jsonify({"ok": True, "jobs": jobs, "count": len(jobs)})
    except Exception as e:
        logger.error(f"list_fallback_jobs_endpoint error: {e}")
        return make_response(jsonify({"error": "Jobs list failed", "details": str(e)}), 500)


# ---------- Admin: List RQ Failed Jobs ----------
@app.route("/admin/fallback/failed", methods=["GET"])
def list_failed_rq_jobs():
    """List recent RQ failed jobs with metadata (admin only)."""
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        if not expected_key or api_key != expected_key:
            return make_response(jsonify({"error": "Unauthorized - valid API key required"}), 401)
        
        redis_url = os.getenv('REDIS_URL') or os.getenv('ADMIN_LIMITER_REDIS_URL')
        if not redis_url:
            return make_response(jsonify({"error": "REDIS_URL not configured"}), 503)
        
        try:
            import redis
            from rq import Queue
            from rq.registry import FailedJobRegistry
            from rq.job import Job
        except Exception as e:
            return make_response(jsonify({"error": "RQ dependencies unavailable", "details": str(e)}), 503)
        
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
        conn = redis.from_url(redis_url)
        reg = FailedJobRegistry('fallback', connection=conn)
        job_ids = reg.get_job_ids()[:limit]
        
        failed_jobs = []
        for jid in job_ids:
            try:
                job = Job.fetch(jid, connection=conn)
                meta = job.meta or {}
                failed_jobs.append({
                    "job_id": jid,
                    "status": job.get_status(),
                    "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
                    "ended_at": job.ended_at.isoformat() if job.ended_at else None,
                    "correlation_id": meta.get('correlation_id'),
                    "acting_email": meta.get('acting_email'),
                    "country": meta.get('country'),
                    "region": meta.get('region'),
                    "attempts": meta.get('attempts'),
                    "max_retries": meta.get('max_retries'),
                    "exc_info": (job.exc_info or '').splitlines()[-1] if job.exc_info else None,
                })
            except Exception as e:
                failed_jobs.append({"job_id": jid, "error": str(e)})
        
        return jsonify({"ok": True, "failed_jobs": failed_jobs, "count": len(failed_jobs)})
    except Exception as e:
        logger.error(f"list_failed_rq_jobs error: {e}")
        return make_response(jsonify({"error": "Failed jobs list error", "details": str(e)}), 500)


# ---------- Ops Stub: Public fallback trigger (intentionally non-operational) ----------
@app.route("/api/fallback/trigger", methods=["POST", "OPTIONS"])  # stub for future use
def public_fallback_trigger_stub():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    # For safety, expose only admin path for now
    return _build_cors_response(make_response(jsonify({
        "ok": False,
        "message": "Use /admin/fallback/trigger with X-API-Key",
    }), 403))


# ============================================================================
# GEOCODING ENDPOINTS
# ============================================================================

@app.route('/api/geocode', methods=['POST', 'OPTIONS'])
def geocode_location():
    """
    Geocode a single location.
    
    POST /api/geocode
    {
        "location": "Paris, France"
    }
    """
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from geocoding_service import geocode as geocode_svc
        
        data = request.json
        location = data.get('location')
        
        if not location:
            return _build_cors_response(jsonify({'error': 'location required'}), 400)
        
        result = geocode_svc(location)
        
        if result:
            return _build_cors_response(jsonify({
                'success': True,
                'location': location,
                'result': result
            }))
        else:
            return _build_cors_response(jsonify({
                'success': False,
                'error': 'Geocoding failed'
            }), 404)
            
    except Exception as e:
        logger.error(f"[geocode] Error: {e}")
        return _build_cors_response(jsonify({'error': str(e)}), 500)


@app.route('/api/geocode/batch', methods=['POST', 'OPTIONS'])
def batch_geocode_locations():
    """
    Geocode multiple locations.
    
    POST /api/geocode/batch
    {
        "locations": ["Paris, France", "London, UK", "Berlin, Germany"],
        "max_api_calls": 50
    }
    """
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from geocoding_service import batch_geocode, get_quota_status
        
        data = request.json
        locations = data.get('locations', [])
        max_api_calls = data.get('max_api_calls', 100)
        
        if not locations:
            return _build_cors_response(jsonify({'error': 'locations array required'}), 400)
        
        results = batch_geocode(locations, max_api_calls=max_api_calls)
        
        return _build_cors_response(jsonify({
            'success': True,
            'total_requested': len(locations),
            'total_geocoded': len(results),
            'results': results,
            'quota': get_quota_status()
        }))
        
    except Exception as e:
        logger.error(f"[batch_geocode] Error: {e}")
        return _build_cors_response(jsonify({'error': str(e)}), 500)


@app.route('/api/geocode/quota', methods=['GET', 'OPTIONS'])
def geocoding_quota():
    """
    Check OpenCage API quota status.
    
    GET /api/geocode/quota
    """
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from geocoding_service import get_quota_status
        return _build_cors_response(jsonify(get_quota_status()))
    except Exception as e:
        logger.error(f"[quota] Error: {e}")
        return _build_cors_response(jsonify({'error': str(e)}), 500)


# ============================================================================
# PROXIMITY ALERT ENDPOINTS
# ============================================================================

@app.route('/api/proximity/threats/<int:traveler_id>', methods=['GET', 'OPTIONS'])
def get_proximity_threats(traveler_id):
    """
    Get threats near a specific traveler.
    
    GET /api/proximity/threats/123?hours=24
    """
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from proximity_alerts import find_threats_near_traveler
        
        hours = request.args.get('hours', 24, type=int)
        
        threats = find_threats_near_traveler(traveler_id, hours_lookback=hours)
        
        return _build_cors_response(jsonify({
            'success': True,
            'traveler_id': traveler_id,
            'hours_lookback': hours,
            'threat_count': len(threats),
            'threats': threats
        }))
        
    except Exception as e:
        logger.error(f"[proximity_threats] Error: {e}")
        return _build_cors_response(jsonify({'error': str(e)}), 500)


@app.route('/api/proximity/location', methods=['POST', 'OPTIONS'])
def proximity_by_location():
    """
    Get threats near any location.
    
    POST /api/proximity/location
    {
        "lat": 48.8566,
        "lon": 2.3522,
        "radius_km": 50,
        "days": 7,
        "sources": ["gdelt", "rss"]
    }
    """
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from proximity_alerts import find_threats_near_location
        
        data = request.json
        
        lat = data.get('lat')
        lon = data.get('lon')
        radius_km = data.get('radius_km', 50)
        days = data.get('days', 7)
        sources = data.get('sources')
        
        if lat is None or lon is None:
            return _build_cors_response(jsonify({'error': 'lat and lon required'}), 400)
        
        threats = find_threats_near_location(
            lat=float(lat),
            lon=float(lon),
            radius_km=radius_km,
            days=days,
            sources=sources
        )
        
        return _build_cors_response(jsonify({
            'success': True,
            'location': {'lat': lat, 'lon': lon},
            'radius_km': radius_km,
            'days': days,
            'threat_count': len(threats),
            'threats': threats
        }))
        
    except Exception as e:
        logger.error(f"[proximity_location] Error: {e}")
        return _build_cors_response(jsonify({'error': str(e)}), 500)


@app.route('/api/proximity/history/<int:traveler_id>', methods=['GET', 'OPTIONS'])
def traveler_alert_history(traveler_id):
    """
    Get alert history for a traveler.
    
    GET /api/proximity/history/123?days=30
    """
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    try:
        from proximity_alerts import get_traveler_threat_history
        
        days = request.args.get('days', 30, type=int)
        
        history = get_traveler_threat_history(traveler_id, days=days)
        
        return _build_cors_response(jsonify({
            'success': True,
            'traveler_id': traveler_id,
            'days': days,
            'alert_count': len(history),
            'alerts': history
        }))
        
    except Exception as e:
        logger.error(f"[alert_history] Error: {e}")
        return _build_cors_response(jsonify({'error': str(e)}), 500)


# ============================================================================
# ADMIN: GEOCODING & PROXIMITY
# ============================================================================

@app.route('/admin/proximity/check-all', methods=['POST'])
def admin_check_all_travelers():
    """
    Manually trigger proximity check for all travelers.
    
    POST /admin/proximity/check-all
    {
        "send_alerts": true
    }
    """
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        from proximity_alerts import check_all_travelers
        
        data = request.json or {}
        send_alerts = data.get('send_alerts', False)
        
        result = check_all_travelers(send_alerts=send_alerts)
        
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        logger.error(f"[check_all] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/geocode/backfill', methods=['POST'])
def admin_geocode_backfill():
    """
    Geocode missing coordinates in a table.
    
    POST /admin/geocode/backfill
    {
        "table": "raw_alerts",
        "id_column": "id",
        "location_column": "location",
        "limit": 100
    }
    """
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        from geocoding_service import geocode_and_update_table
        
        data = request.json
        
        table = data.get('table')
        id_column = data.get('id_column', 'id')
        location_column = data.get('location_column', 'location')
        limit = data.get('limit', 100)
        
        if not table:
            return jsonify({'error': 'table required'}), 400
        
        geocode_and_update_table(
            table_name=table,
            id_column=id_column,
            location_column=location_column,
            limit=limit
        )
        
        return jsonify({
            'success': True,
            'message': f'Geocoded up to {limit} rows in {table}'
        })
        
    except Exception as e:
        logger.error(f"[backfill] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/geocode/batch-smart', methods=['POST'])
def batch_geocode_smart_endpoint():
    """
    Smart batch geocoding with deduplication and severity filtering.
    
    POST /admin/geocode/batch-smart
    {
        "limit": 2000,
        "min_severity": 0.3,
        "max_api_calls": 400
    }
    """
    try:
        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        expected_key = os.getenv("ADMIN_API_KEY")
        if not expected_key or api_key != expected_key:
            return jsonify({"error": "Unauthorized - valid API key required"}), 401
        
        from geocoding_service import batch_geocode
        from db_utils import _get_db_connection
        
        data = request.json or {}
        limit = data.get('limit', 2000)
        min_severity = data.get('min_severity', 0.0)
        max_api_calls = data.get('max_api_calls', 400)
        
        # Fetch alerts with missing coordinates, severity-first
        conn = _get_db_connection()
        cur = conn.cursor()
        
        query = """
            SELECT id, location
            FROM alerts
            WHERE (latitude IS NULL OR longitude IS NULL)
              AND location IS NOT NULL
              AND location != ''
              AND (
                CASE 
                  WHEN (score::text) ~ '^[0-9]+(\\.[0-9]+)?$' 
                  THEN (score::text)::numeric 
                  ELSE 0 
                END
              ) >= %s
            ORDER BY 
              CASE 
                WHEN (score::text) ~ '^[0-9]+(\\.[0-9]+)?$' 
                THEN (score::text)::numeric 
                ELSE 0 
              END DESC,
              published DESC
            LIMIT %s
        """
        
        cur.execute(query, (min_severity, limit))
        rows = cur.fetchall()
        
        if not rows:
            cur.close()
            conn.close()
            return jsonify({
                'success': True,
                'processed': 0,
                'message': 'No alerts need geocoding'
            })
        
        # Extract unique locations for batch geocoding
        location_map = {}  # location -> [ids]
        for alert_id, location in rows:
            if location not in location_map:
                location_map[location] = []
            location_map[location].append(alert_id)
        
        unique_locations = list(location_map.keys())
        logger.info(f"[batch-smart] Processing {len(rows)} alerts, {len(unique_locations)} unique locations")
        
        # Batch geocode with deduplication
        geocoded = batch_geocode(unique_locations, max_api_calls=max_api_calls)
        
        # Update alerts with coordinates
        updated = 0
        for location, result in geocoded.items():
            if result.get('latitude') and result.get('longitude'):
                alert_ids = location_map[location]
                cur.execute("""
                    UPDATE alerts
                    SET latitude = %s, longitude = %s
                    WHERE id = ANY(%s)
                """, (result['latitude'], result['longitude'], alert_ids))
                updated += len(alert_ids)
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'processed': len(rows),
            'unique_locations': len(unique_locations),
            'updated': updated,
            'api_calls': len([r for r in geocoded.values() if r.get('source') in ['nominatim', 'opencage']])
        })
        
    except Exception as e:
        logger.error(f"[batch-smart] Error: {e}")
        return jsonify({'error': str(e)}), 500

# -------------------------------------------------------------------
# User Context Endpoints (for Sentinel AI Chat, Threat Map, Travel Risk Map)
# -------------------------------------------------------------------

@app.route("/api/context", methods=["GET", "OPTIONS"])
def context_get_options():
    """Handle OPTIONS preflight for GET /api/context"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return context_get()

@app.route("/api/context", methods=["GET"])
@login_required
def context_get():
    """Get user's current context across all Sentinel AI products"""
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({"error": "Database unavailable"}), 503))
    
    try:
        email = get_logged_in_email()
        
        # Get user ID
        user_row = fetch_one("SELECT id FROM users WHERE email = %s", (email,))
        if not user_row:
            return _build_cors_response(make_response(jsonify({"error": "User not found"}), 404))
        
        user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
        
        # Get context
        ctx_row = fetch_one("SELECT * FROM user_context WHERE user_id = %s", (user_id,))
        
        if not ctx_row:
            # Return empty context
            return _build_cors_response(jsonify({
                "ok": True,
                "investigation": None,
                "recent": [],
                "locations": []
            }))
        
        # Parse JSONB fields
        investigation = ctx_row.get('active_investigation') if isinstance(ctx_row, dict) else None
        recent_queries = ctx_row.get('recent_queries') if isinstance(ctx_row, dict) else None
        saved_locations = ctx_row.get('saved_locations') if isinstance(ctx_row, dict) else None
        
        # Ensure arrays are always lists, never None
        if not isinstance(recent_queries, list):
            recent_queries = []
        if not isinstance(saved_locations, list):
            saved_locations = []
        
        # Limit recent queries to last 10
        recent_queries = recent_queries[-10:]
        
        return _build_cors_response(jsonify({
            "ok": True,
            "investigation": investigation,
            "recent": recent_queries,
            "locations": saved_locations
        }))
        
    except Exception as e:
        logger.error(f"context_get error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Failed to fetch context"}), 500))

@app.route("/api/context", methods=["POST"])
@login_required
def context_post():
    """Update user context (investigation, query, location, or clear)"""
    if execute is None:
        return _build_cors_response(make_response(jsonify({"error": "Database unavailable"}), 503))
    
    try:
        email = get_logged_in_email()
        payload = _json_request()
        
        context_type = payload.get("type", "").lower()
        data = payload.get("data", {})
        
        if not context_type:
            return _build_cors_response(make_response(jsonify({"error": "Missing type field"}), 400))
        
        # Get user ID
        user_row = fetch_one("SELECT id FROM users WHERE email = %s", (email,))
        if not user_row:
            return _build_cors_response(make_response(jsonify({"error": "User not found"}), 404))
        
        user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
        
        if context_type == "investigation":
            # Set active investigation for Sentinel AI Chat
            execute("""
                INSERT INTO user_context (user_id, active_investigation, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (user_id) 
                DO UPDATE SET active_investigation = EXCLUDED.active_investigation, updated_at = NOW()
            """, (user_id, Json(data)))
            
        elif context_type == "query":
            # Append to recent queries array (keep last 10)
            execute("""
                INSERT INTO user_context (user_id, recent_queries, updated_at)
                VALUES (%s, jsonb_build_array(%s), NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET 
                    recent_queries = (
                        SELECT jsonb_agg(elem ORDER BY (elem->>'timestamp') DESC)
                        FROM (
                            SELECT elem 
                            FROM jsonb_array_elements(
                                COALESCE(user_context.recent_queries, '[]'::jsonb) || %s::jsonb
                            ) elem
                            LIMIT 10
                        ) sub
                    ),
                    updated_at = NOW()
            """, (user_id, Json(data), Json([data])))
            
        elif context_type == "location":
            # Add to saved locations (avoid duplicates by checking location name)
            execute("""
                INSERT INTO user_context (user_id, saved_locations, updated_at)
                VALUES (%s, jsonb_build_array(%s), NOW())
                ON CONFLICT (user_id)
                DO UPDATE SET 
                    saved_locations = (
                        CASE 
                            WHEN user_context.saved_locations @> %s::jsonb 
                            THEN user_context.saved_locations
                            ELSE user_context.saved_locations || %s::jsonb
                        END
                    ),
                    updated_at = NOW()
            """, (user_id, Json(data), Json([data]), Json([data])))
            
        elif context_type == "clear":
            # Clear active investigation
            execute("""
                UPDATE user_context 
                SET active_investigation = NULL, updated_at = NOW()
                WHERE user_id = %s
            """, (user_id,))
            
        else:
            return _build_cors_response(make_response(jsonify({"error": f"Invalid type: {context_type}"}), 400))
        
        return _build_cors_response(jsonify({"ok": True, "message": "Context updated"}))
        
    except Exception as e:
        logger.error(f"context_post error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Failed to update context"}), 500))

@app.route("/api/context/search", methods=["GET", "OPTIONS"])
def context_search_options():
    """Handle OPTIONS preflight for GET /api/context/search"""
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return context_search()

@app.route("/api/context/search", methods=["GET"])
@login_required
def context_search():
    """Unified search across locations/threats for Threat Map and Travel Risk Map"""
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "Database unavailable"}), 503))
    
    try:
        query = request.args.get("q", "").strip()
        
        if len(query) < 3:
            return _build_cors_response(jsonify({
                "ok": True,
                "locations": [],
                "travel": None
            }))
        
        # Search alerts for location matches
        locations = fetch_all("""
            SELECT 
                COALESCE(city, country) as location,
                COUNT(*) as count,
                AVG(lat) as lat,
                AVG(lon) as lon
            FROM alerts
            WHERE 
                (city ILIKE %s OR country ILIKE %s OR title ILIKE %s)
                AND lat IS NOT NULL AND lon IS NOT NULL
            GROUP BY COALESCE(city, country)
            ORDER BY count DESC
            LIMIT 5
        """, (f"%{query}%", f"%{query}%", f"%{query}%"))
        
        # For travel assessment, use first location match
        travel = None
        if locations and len(locations) > 0:
            first = locations[0]
            travel = {
                "label": first.get('location') if isinstance(first, dict) else first[0],
                "lat": float(first.get('lat') if isinstance(first, dict) else first[2]),
                "lon": float(first.get('lon') if isinstance(first, dict) else first[3])
            }
        
        # Format location results
        location_results = []
        for row in (locations or []):
            if isinstance(row, dict):
                location_results.append({
                    "location": row.get('location', 'Unknown'),
                    "count": int(row.get('count', 0)),
                    "lat": float(row.get('lat', 0)),
                    "lon": float(row.get('lon', 0)),
                    "zoom": 12
                })
            else:
                location_results.append({
                    "location": row[0] if row[0] else 'Unknown',
                    "count": int(row[1]) if len(row) > 1 else 0,
                    "lat": float(row[2]) if len(row) > 2 else 0,
                    "lon": float(row[3]) if len(row) > 3 else 0,
                    "zoom": 12
                })
        
        return _build_cors_response(jsonify({
            "ok": True,
            "locations": location_results,
            "travel": travel
        }))
        
    except Exception as e:
        logger.error(f"context_search error: {e}")
        return _build_cors_response(make_response(jsonify({"error": "Search failed"}), 500))

# -------------------------------------------------------------------
# New Feature-Gated Endpoints (plans + usage) — incremental rollout
# -------------------------------------------------------------------

@app.route('/api/sentinel-chat', methods=['POST'])
@login_required
def sentinel_chat():
    """Chat endpoint with FREE lifetime quota and paid monthly quota.
    FREE plan: uses users.lifetime_chat_messages against PLAN_FEATURES['FREE']['chat_messages_lifetime'].
    Paid plans: use feature_usage monthly counter 'chat_messages_monthly'.
    
    Returns response with quality metadata for transparency.
    """
    import time
    from datetime import datetime, timezone
    
    request_start = time.perf_counter()
    
    try:
        email = get_logged_in_email()
        from plan_utils import get_plan_limits
        limits = get_plan_limits(email)
        plan = limits['plan']
        payload = request.get_json(silent=True) or {}
        message = (payload.get('message') or '').strip()
        if not message:
            return _build_cors_response(make_response(jsonify({'error': 'Message required'}), 400))
        if fetch_one is None or execute is None:
            return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
        
        # FREE plan lifetime gating
        if plan == 'FREE':
            lifetime_limit = get_plan_feature(plan, 'chat_messages_lifetime') or 0
            user_row = fetch_one('SELECT id, lifetime_chat_messages FROM users WHERE email=%s', (email,))
            if not user_row:
                return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
            if isinstance(user_row, dict):
                user_id = user_row['id']; lifetime_used = int(user_row.get('lifetime_chat_messages') or 0)
            else:
                user_id = user_row[0]; lifetime_used = int(user_row[1] or 0) if len(user_row)>1 else 0
            if lifetime_used >= lifetime_limit:
                return _build_cors_response(make_response(jsonify({
                    'error': 'Free tier chat quota reached',
                    'feature_locked': True,
                    'required_plan': 'PRO',
                    'usage': {'used': lifetime_used,'limit': lifetime_limit,'scope': 'lifetime'}
                }), 403))
            
            # Produce advisory then increment lifetime counter
            advisory = f"Echo: {message[:512]}"
            execute('UPDATE users SET lifetime_chat_messages = COALESCE(lifetime_chat_messages,0)+1 WHERE id=%s', (user_id,))
            
            # Add metadata for FREE tier echo responses
            processing_time_ms = int((time.perf_counter() - request_start) * 1000)
            current_time = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            
            return _build_cors_response(jsonify({
                'ok': True,
                'reply': advisory,
                'usage': {'used': lifetime_used + 1,'limit': lifetime_limit,'scope': 'lifetime'},
                'plan': plan,
                'metadata': {
                    'sources_count': 0,
                    'confidence_score': 0.0,
                    'last_updated': current_time,
                    'can_refresh': False,
                    'processing_time_ms': processing_time_ms
                }
            }))
        
        # Paid plan monthly gating
        monthly_limit = get_plan_feature(plan, 'chat_messages_monthly')
        user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
        if not user_row:
            return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
        user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
        used_row = fetch_one("SELECT usage_count FROM feature_usage WHERE user_id=%s AND feature='chat_messages_monthly' AND period_start=date_trunc('month', current_date)::date", (user_id,))
        used = used_row['usage_count'] if isinstance(used_row, dict) else (used_row[0] if used_row else 0)
        if monthly_limit is not None and monthly_limit != float('inf') and used >= monthly_limit:
            return _build_cors_response(make_response(jsonify({
                'error': 'Monthly chat quota reached',
                'feature_locked': True,
                'required_plan': 'BUSINESS' if plan == 'PRO' else ('ENTERPRISE' if plan == 'BUSINESS' else plan),
                'usage': {'used': used,'limit': monthly_limit,'scope': 'monthly'}
            }), 403))
        
        # For paid plans, call the full chat handler which now includes metadata
        # This will return proper intelligence with sources and confidence
        try:
            from chat_handler import handle_user_query
            response = handle_user_query(
                message=message,
                email=email,
                body=payload
            )
            
            # Increment monthly usage via function
            try:
                execute('SELECT increment_feature_usage(%s,%s)', (user_id, 'chat_messages_monthly'))
            except Exception:
                pass
            
            # The response already includes metadata from handle_user_query
            return _build_cors_response(jsonify({
                'ok': True,
                **response
            }))
            
        except Exception as e:
            logger.error('chat_handler call failed: %s', e)
            # Fallback to echo with metadata
            advisory = f"Echo: {message[:512]}"
            try:
                execute('SELECT increment_feature_usage(%s,%s)', (user_id, 'chat_messages_monthly'))
            except Exception:
                pass
            
            processing_time_ms = int((time.perf_counter() - request_start) * 1000)
            current_time = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            
            return _build_cors_response(jsonify({
                'ok': True,
                'reply': advisory,
                'usage': {'used': used + 1,'limit': monthly_limit,'scope': 'monthly'},
                'plan': plan,
                'metadata': {
                    'sources_count': 0,
                    'confidence_score': 0.0,
                    'last_updated': current_time,
                    'can_refresh': False,
                    'processing_time_ms': processing_time_ms
                }
            }))
            
    except Exception as e:
        logger.error('sentinel_chat error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Chat failed'}), 500))

@app.route('/api/map-alerts/gated', methods=['GET'])
@login_required
def map_alerts_gated():
    """Map alerts with plan-based historical window gating."""
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({'error': 'Database unavailable'}), 503))
    try:
        email = get_logged_in_email()
        from plan_utils import get_plan_limits
        limits = get_plan_limits(email)
        plan = limits['plan']
        requested_days = int(request.args.get('days', limits.get('map_days', 2)))
        max_days = get_plan_feature(plan, 'map_access_days') or limits.get('map_days', 2)
        if requested_days > max_days:
            return _build_cors_response(make_response(jsonify({'error': f'Plan {plan} allows up to {max_days} days','feature_locked': True,'required_plan': 'PRO' if plan == 'FREE' else ('BUSINESS' if plan == 'PRO' else 'ENTERPRISE')}), 403))
        q = """
            SELECT uuid, published, source, title, link, region, country, city,
                   threat_level, score, confidence, lat, lon
            FROM alerts
            WHERE published >= NOW() - make_interval(days => %s)
            ORDER BY published DESC NULLS LAST
            LIMIT 500
        """
        rows = fetch_all(q, (requested_days,)) or []
        features = []
        for r in rows:
            d = r if isinstance(r, dict) else None
            lat_val = (d.get('lat') if d else (r[11] if len(r) > 11 else None))
            lon_val = (d.get('lon') if d else (r[12] if len(r) > 12 else None))
            if lat_val is None or lon_val is None:
                continue
            props = dict(d) if d else {
                'uuid': r[0],'published': r[1],'source': r[2],'title': r[3],'link': r[4],'region': r[5],'country': r[6],'city': r[7],'threat_level': r[8],'score': r[9],'confidence': r[10]
            }
            props.pop('lat', None); props.pop('lon', None)
            features.append({'type': 'Feature','geometry': {'type': 'Point','coordinates': [float(lon_val), float(lat_val)]},'properties': props})
        return _build_cors_response(jsonify({'ok': True,'items': rows,'features': features,'window_days': requested_days,'plan_limit_days': max_days,'plan': plan}))
    except Exception as e:
        logger.error('map_alerts_gated error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Map alerts failed'}), 500))

@app.route('/api/travel-risk/assess', methods=['POST'])
@login_required
@check_usage_limit('travel_assessments_monthly', increment=True)
def travel_risk_assess():
    """Simple travel risk assessment stub (usage gated)."""
    payload = request.get_json(silent=True) or {}
    destination = (payload.get('destination') or '').strip()
    if not destination:
        return _build_cors_response(make_response(jsonify({'error': 'destination required'}), 400))
    # Placeholder scoring logic
    assessment = {
        'destination': destination,
        'risk_level': 'medium',
        'score': 55,
        'factors': ['Political stability moderate','Health infrastructure adequate']
    }
    return _build_cors_response(jsonify({'ok': True,'assessment': assessment}))

@app.route('/api/timeline', methods=['GET'])
@login_required
@requires_feature('timeline_access')
def timeline_gated():
    """Delegates to existing analytics_timeline with feature gate."""
    return analytics_timeline()

@app.route('/api/stats/overview/gated', methods=['GET'])
@login_required
def stats_overview_gated():
    """Extended stats with tiered detail level."""
    try:
        email = get_logged_in_email()
        from plan_utils import get_plan_limits
        limits = get_plan_limits(email)
        level = get_plan_feature(limits['plan'], 'statistics_dashboard')
        if not level:
            return _build_cors_response(make_response(jsonify({'error': 'Statistics require PRO plan','feature_locked': True,'required_plan': 'PRO'}), 403))
        # Call base stats overview
        base_resp = stats_overview()
        data = base_resp.get_json() if hasattr(base_resp, 'get_json') else {}
        enriched = dict(data)
        if level in ('advanced','custom'):
            enriched.setdefault('top_regions', data.get('top_regions', []))
            enriched.setdefault('weekly_trends', data.get('weekly_trends', []))
        if level == 'custom':
            enriched['custom_metrics'] = {'proprietary_index': 87.3}
        enriched['dashboard_level'] = level
        return _build_cors_response(jsonify(enriched))
    except Exception as e:
        logger.error('stats_overview_gated error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Stats failed'}), 500))

@app.route('/api/monitoring/searches', methods=['GET'])
@login_required
def saved_searches_list():
    """List saved searches with plan limit info."""
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({'error': 'Database unavailable'}), 503))
    email = get_logged_in_email()
    user_row = fetch_one('SELECT id, plan FROM users WHERE email=%s', (email,)) if fetch_one else None
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    plan = (user_row['plan'] if isinstance(user_row, dict) else user_row[1] or 'FREE').upper()
    rows = fetch_all('SELECT id, name, query, alert_enabled, alert_frequency, created_at FROM saved_searches WHERE user_id=%s ORDER BY created_at DESC', (user_id,)) or []
    limit = get_plan_feature(plan, 'saved_searches')
    return _build_cors_response(jsonify({'ok': True,'searches': rows,'limit': limit,'used': len(rows),'plan': plan}))

@app.route('/api/monitoring/searches', methods=['POST'])
@login_required
def saved_searches_create():
    """Create saved search respecting plan limit."""
    if fetch_one is None or execute is None:
        return _build_cors_response(make_response(jsonify({'error': 'Database unavailable'}), 503))
    email = get_logged_in_email()
    user_row = fetch_one('SELECT id, plan FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    plan = (user_row['plan'] if isinstance(user_row, dict) else user_row[1] or 'FREE').upper()
    limit = get_plan_feature(plan, 'saved_searches')
    count_row = fetch_one('SELECT COUNT(*) AS c FROM saved_searches WHERE user_id=%s', (user_id,))
    current = (count_row['c'] if isinstance(count_row, dict) else count_row[0]) if count_row else 0
    if limit is not None and limit != 0 and current >= limit:
        return _build_cors_response(make_response(jsonify({'error': f'Max saved searches ({limit}) reached','feature_locked': True,'required_plan': 'BUSINESS' if plan == 'PRO' else 'PRO'}), 403))
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    query = payload.get('query') or {}
    alert_enabled = bool(payload.get('alert_enabled', True))
    alert_frequency = (payload.get('alert_frequency') or 'daily').lower()
    if not name:
        return _build_cors_response(make_response(jsonify({'error': 'name required'}), 400))
    try:
        execute('INSERT INTO saved_searches (user_id, name, query, alert_enabled, alert_frequency) VALUES (%s,%s,%s,%s,%s)', (user_id, name, Json(query), alert_enabled, alert_frequency))
        new_id_row = fetch_one('SELECT id FROM saved_searches WHERE user_id=%s AND name=%s ORDER BY id DESC LIMIT 1', (user_id, name))
        new_id = new_id_row['id'] if isinstance(new_id_row, dict) else new_id_row[0]
        return _build_cors_response(jsonify({'ok': True,'id': new_id}))
    except Exception as e:
        logger.error('saved_searches_create error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'create failed'}), 500))

@app.route('/api/export/alerts', methods=['POST'])
@login_required
def export_alerts():
    """Export alerts in formats gated by plan."""
    email = get_logged_in_email()
    from plan_utils import get_plan_limits
    limits = get_plan_limits(email)
    plan = limits['plan']
    payload = request.get_json(silent=True) or {}
    fmt = (payload.get('format') or 'csv').lower()
    allowed = get_plan_feature(plan, 'map_export')
    if not allowed:
        return _build_cors_response(make_response(jsonify({'error': 'Export requires PRO plan','feature_locked': True,'required_plan': 'PRO'}), 403))
    if allowed == 'csv' and fmt != 'csv':
        return _build_cors_response(make_response(jsonify({'error': f'{fmt.upper()} export requires BUSINESS plan','feature_locked': True,'required_plan': 'BUSINESS'}), 403))
    # Placeholder export processing (replace with actual file generation)
    alert_ids = payload.get('alert_ids') or []
    file_url = f"/downloads/alerts_export_{fmt}_{len(alert_ids)}.dat"
    return _build_cors_response(jsonify({'ok': True,'download_url': file_url,'format': fmt,'plan': plan}))

@app.route('/api/user/plan', methods=['GET'])
@login_required
def user_plan_info():
    """Return current user plan + feature snapshot."""
    email = get_logged_in_email()
    user_row = fetch_one('SELECT id, plan, is_trial, trial_ends_at FROM users WHERE email=%s', (email,)) if fetch_one else None
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    plan = (user_row['plan'] if isinstance(user_row, dict) else user_row[1] or 'FREE').upper()
    trial_ends = user_row.get('trial_ends_at') if isinstance(user_row, dict) else None
    features = PLAN_FEATURES.get(plan, {})
    usage_chat_row = fetch_one("SELECT usage_count FROM feature_usage WHERE user_id=(SELECT id FROM users WHERE email=%s) AND feature='chat_messages_monthly' AND period_start=date_trunc('month', current_date)::date", (email,)) if fetch_one else None
    usage_chat = usage_chat_row['usage_count'] if isinstance(usage_chat_row, dict) else (usage_chat_row[0] if usage_chat_row else 0)
    return _build_cors_response(jsonify({'ok': True,'plan': plan,'is_trial': bool(user_row.get('is_trial') if isinstance(user_row, dict) else False),'trial_ends_at': trial_ends.isoformat() if trial_ends else None,'features': features,'usage': {'chat_messages_monthly_used': usage_chat,'chat_messages_monthly_limit': get_plan_feature(plan,'chat_messages_monthly')}}))

@app.route('/api/user/upgrade', methods=['POST'])
@login_required
def user_plan_upgrade():
    """Upgrade plan (records in plan_changes)."""
    payload = request.get_json(silent=True) or {}
    target = (payload.get('plan') or '').upper()
    if target not in ('PRO','BUSINESS','ENTERPRISE'):
        return _build_cors_response(make_response(jsonify({'error': 'Invalid plan'}), 400))
    email = get_logged_in_email()
    current_row = fetch_one('SELECT id, plan FROM users WHERE email=%s', (email,)) if fetch_one else None
    if not current_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = current_row['id'] if isinstance(current_row, dict) else current_row[0]
    old_plan = (current_row['plan'] if isinstance(current_row, dict) else current_row[1] or 'FREE').upper()
    if old_plan == target:
        return _build_cors_response(jsonify({'ok': True,'message': 'Already on requested plan','plan': old_plan}))
    try:
        if execute:
            execute('INSERT INTO plan_changes (user_id, from_plan, to_plan, reason) VALUES (%s,%s,%s,%s)', (user_id, old_plan, target, 'upgrade'))
            execute('UPDATE users SET plan=%s WHERE id=%s', (target, user_id))
        return _build_cors_response(jsonify({'ok': True,'message': f'Upgraded from {old_plan} to {target}','new_plan': target}))
    except Exception as e:
        logger.error('user_plan_upgrade error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Upgrade failed'}), 500))

@app.route('/api/user/trial/start', methods=['POST'])
@login_required
def user_trial_start():
    """Start a trial for the authenticated FREE user (default PRO)."""
    try:
        from utils.trial_manager import start_trial
    except Exception as e:
        logger.error('trial_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Trial system unavailable'}), 500))
    data = request.get_json(silent=True) or {}
    plan = (data.get('plan') or 'PRO').upper()
    email = get_logged_in_email()
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    user_row = fetch_one('SELECT id, email, plan, is_trial FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user = user_row if isinstance(user_row, dict) else {
        'id': user_row[0], 'email': email, 'plan': user_row[2] if len(user_row)>2 else 'FREE', 'is_trial': user_row[3] if len(user_row)>3 else False
    }
    try:
        result = start_trial(user, plan=plan)
        return _build_cors_response(jsonify({'ok': True, **result}))
    except ValueError as ve:
        return _build_cors_response(make_response(jsonify({'error': str(ve)}), 400))
    except Exception as e:
        logger.error('user_trial_start error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Trial start failed'}), 500))

@app.route('/api/user/trial/end', methods=['POST'])
@login_required
def user_trial_end():
    """End current trial; optionally convert to paid (keep plan)."""
    try:
        from utils.trial_manager import end_trial
    except Exception as e:
        logger.error('trial_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Trial system unavailable'}), 500))
    data = request.get_json(silent=True) or {}
    convert = bool(data.get('convert_to_paid', False))
    email = get_logged_in_email()
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    user_row = fetch_one('SELECT id, email, plan, is_trial FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user = user_row if isinstance(user_row, dict) else {
        'id': user_row[0], 'email': email, 'plan': user_row[2] if len(user_row)>2 else 'FREE', 'is_trial': user_row[3] if len(user_row)>3 else False
    }
    try:
        result = end_trial(user, convert_to_paid=convert)
        return _build_cors_response(jsonify({'ok': True, **result}))
    except ValueError as ve:
        return _build_cors_response(make_response(jsonify({'error': str(ve)}), 400))
    except Exception as e:
        logger.error('user_trial_end error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Trial end failed'}), 500))

@app.route('/api/user/trial/status', methods=['GET'])
@login_required
def user_trial_status():
    """Return trial status snapshot for authenticated user."""
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    email = get_logged_in_email()
    row = fetch_one('SELECT plan, is_trial, trial_started_at, trial_ends_at FROM users WHERE email=%s', (email,))
    if not row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    if isinstance(row, dict):
        plan = row.get('plan') or 'FREE'
        is_trial = bool(row.get('is_trial'))
        started = row.get('trial_started_at')
        ends = row.get('trial_ends_at')
    else:
        plan = row[0] if len(row)>0 else 'FREE'
        is_trial = bool(row[1]) if len(row)>1 else False
        started = row[2] if len(row)>2 else None
        ends = row[3] if len(row)>3 else None
    return _build_cors_response(jsonify({
        'ok': True,
        'plan': (plan or 'FREE').upper(),
        'is_trial': is_trial,
        'trial_started_at': started.isoformat() + 'Z' if started else None,
        'trial_ends_at': ends.isoformat() + 'Z' if ends else None,
        'can_start_trial': (not is_trial) and ((plan or 'FREE').upper() in ['FREE',''])
    }))

@app.route('/api/cron/check-trials', methods=['POST'])
def cron_check_trials():
    """Cron endpoint to check and expire trials. Secured via X-Cron-Secret header."""
    from utils.trial_manager import check_expired_trials
    secret_header = request.headers.get('X-Cron-Secret')
    expected = os.environ.get('CRON_SECRET')
    if not expected or secret_header != expected:
        return _build_cors_response(make_response(jsonify({'error': 'Unauthorized'}), 401))
    try:
        expired_count = check_expired_trials()
        return _build_cors_response(jsonify({'ok': True, 'expired_trials': expired_count}))
    except Exception as e:
        logger.error('cron_check_trials error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Cron execution failed'}), 500))

# ============================================
# Chat Thread Management (10 Comprehensive Endpoints)
# ============================================

@app.route('/api/chat/threads', methods=['POST'])
@login_required
def chat_threads_create():
    """1. Create thread with dual-limit validation."""
    try:
        from utils.thread_manager import create_thread
        from plan_utils import get_plan_limits
        from config.plans import get_plan_feature
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    payload = request.get_json(silent=True) or {}
    title = (payload.get('title') or '').strip()
    investigation_topic = payload.get('investigation_topic')
    messages = payload.get('messages') or []
    
    if not title:
        return _build_cors_response(make_response(jsonify({'error': 'title required'}), 400))
    if not messages:
        return _build_cors_response(make_response(jsonify({'error': 'messages required'}), 400))
    
    try:
        result = create_thread(user_id, plan, title, messages, investigation_topic)
        return _build_cors_response(jsonify({'ok': True, **result}), 201)
    except ValueError as ve:
        msg = str(ve)
        can_archive = get_plan_feature(plan, 'can_archive_threads', False)
        
        # Detect error type
        if 'active threads' in msg.lower():
            suggestion = "Archive old threads to continue." if can_archive else "Delete an old thread or upgrade to PRO for 50 threads + archiving."
            return _build_cors_response(make_response(jsonify({
                'error': msg,
                'feature_locked': True,
                'required_plan': 'PRO',
                'can_archive': can_archive,
                'suggestion': suggestion
            }), 403))
        elif 'per-thread limit' in msg.lower():
            return _build_cors_response(make_response(jsonify({
                'error': msg,
                'feature_locked': True,
                'required_plan': 'PRO'
            }), 403))
        elif 'monthly' in msg.lower():
            return _build_cors_response(make_response(jsonify({
                'error': msg,
                'feature_locked': True
            }), 403))
        return _build_cors_response(make_response(jsonify({'error': msg}), 403))
    except Exception as e:
        logger.error('chat_threads_create error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread creation failed'}), 500))

@app.route('/api/chat/threads', methods=['GET'])
@login_required
def chat_threads_list():
    """2. List threads with pagination and filtering."""
    try:
        from utils.thread_manager import list_threads
        from plan_utils import get_plan_limits
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    archived = request.args.get('archived', 'false').lower()
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    
    try:
        result = list_threads(user_id, plan, archived, page, limit)
        return _build_cors_response(jsonify({'ok': True, **result}))
    except Exception as e:
        logger.error('chat_threads_list error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread list failed'}), 500))

@app.route('/api/chat/threads/<thread_uuid>', methods=['GET'])
@login_required
def chat_threads_get(thread_uuid):
    """3. Get full thread with all messages."""
    try:
        from utils.thread_manager import get_thread
        from plan_utils import get_plan_limits
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    try:
        result = get_thread(user_id, plan, thread_uuid)
        if not result:
            return _build_cors_response(make_response(jsonify({'error': 'Thread not found'}), 404))
        return _build_cors_response(jsonify({'ok': True, **result}))
    except Exception as e:
        logger.error('chat_threads_get error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread retrieval failed'}), 500))

@app.route('/api/chat/threads/<thread_uuid>/messages', methods=['POST'])
@login_required
def chat_threads_add_messages(thread_uuid):
    """4. Add messages to existing thread."""
    try:
        from utils.thread_manager import add_messages, get_usage_stats, get_thread_limits
        from plan_utils import get_plan_limits
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    payload = request.get_json(silent=True) or {}
    messages = payload.get('messages') or []
    
    if not messages:
        return _build_cors_response(make_response(jsonify({'error': 'messages required'}), 400))
    
    try:
        result = add_messages(user_id, plan, thread_uuid, messages)
        return _build_cors_response(jsonify({'ok': True, **result}), 201)
    except ValueError as ve:
        msg = str(ve)
        
        if 'message limit' in msg.lower() or 'thread has reached' in msg.lower():
            # Thread full error
            usage = get_usage_stats(user_id, plan)
            thread_limits = get_thread_limits(plan)
            return _build_cors_response(make_response(jsonify({
                'error': msg,
                'feature_locked': True,
                'thread_full': True,
                'usage': {
                    'active_threads': usage['active_threads'],
                    'threads_limit': thread_limits['threads_max']
                },
                'suggestion': "Save this thread and start a new conversation, or upgrade to PRO for 50 messages per thread."
            }), 403))
        elif 'monthly' in msg.lower():
            return _build_cors_response(make_response(jsonify({
                'error': msg,
                'feature_locked': True
            }), 403))
        elif 'not found' in msg.lower():
            return _build_cors_response(make_response(jsonify({'error': msg}), 404))
        return _build_cors_response(make_response(jsonify({'error': msg}), 400))
    except Exception as e:
        logger.error('chat_threads_add_messages error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Message append failed'}), 500))

@app.route('/api/chat/threads/<thread_uuid>', methods=['PATCH'])
@login_required
def chat_threads_update_title(thread_uuid):
    """5. Update thread title (metadata only)."""
    try:
        from utils.thread_manager import update_title
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    payload = request.get_json(silent=True) or {}
    title = (payload.get('title') or '').strip()
    
    if not title:
        return _build_cors_response(make_response(jsonify({'error': 'title required'}), 400))
    
    try:
        result = update_title(user_id, thread_uuid, title)
        if not result:
            return _build_cors_response(make_response(jsonify({'error': 'Thread not found'}), 404))
        return _build_cors_response(jsonify({'ok': True, 'thread': result}))
    except Exception as e:
        logger.error('chat_threads_update_title error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Title update failed'}), 500))

@app.route('/api/chat/threads/<thread_uuid>/archive', methods=['POST'])
@login_required
def chat_threads_archive(thread_uuid):
    """6. Archive thread (PRO+ only)."""
    try:
        from utils.thread_manager import archive_thread
        from plan_utils import get_plan_limits
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    try:
        result = archive_thread(user_id, plan, thread_uuid)
        if not result:
            return _build_cors_response(make_response(jsonify({'error': 'Thread not found or already archived'}), 404))
        return _build_cors_response(jsonify({'ok': True, **result}))
    except ValueError as ve:
        msg = str(ve)
        if 'requires PRO' in msg:
            return _build_cors_response(make_response(jsonify({
                'error': msg,
                'feature_locked': True,
                'required_plan': 'PRO'
            }), 403))
        return _build_cors_response(make_response(jsonify({'error': msg}), 400))
    except Exception as e:
        logger.error('chat_threads_archive error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread archive failed'}), 500))

@app.route('/api/chat/threads/<thread_uuid>/unarchive', methods=['POST'])
@login_required
def chat_threads_unarchive(thread_uuid):
    """7. Restore thread from archive."""
    try:
        from utils.thread_manager import unarchive_thread
        from plan_utils import get_plan_limits
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    try:
        result = unarchive_thread(user_id, plan, thread_uuid)
        if not result:
            return _build_cors_response(make_response(jsonify({'error': 'Thread not found in archive'}), 404))
        return _build_cors_response(jsonify({'ok': True, **result}))
    except ValueError as ve:
        msg = str(ve)
        if 'Max active' in msg:
            return _build_cors_response(make_response(jsonify({
                'error': msg,
                'feature_locked': True
            }), 403))
        return _build_cors_response(make_response(jsonify({'error': msg}), 400))
    except Exception as e:
        logger.error('chat_threads_unarchive error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread unarchive failed'}), 500))

@app.route('/api/chat/threads/<thread_uuid>', methods=['DELETE'])
@login_required
def chat_threads_delete(thread_uuid):
    """8. Soft delete thread (30-day restore window)."""
    try:
        from utils.thread_manager import delete_thread
        from plan_utils import get_plan_limits
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    try:
        result = delete_thread(user_id, plan, thread_uuid)
        if not result:
            return _build_cors_response(make_response(jsonify({'error': 'Thread not found'}), 404))
        return _build_cors_response(jsonify({'ok': True, **result}))
    except Exception as e:
        logger.error('chat_threads_delete error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread deletion failed'}), 500))

@app.route('/api/chat/threads/<thread_uuid>/restore', methods=['POST'])
@login_required
def chat_threads_restore(thread_uuid):
    """9. Restore soft-deleted thread (within 30 days)."""
    try:
        from utils.thread_manager import restore_thread, get_usage_stats
        from plan_utils import get_plan_limits
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    try:
        result = restore_thread(user_id, plan, thread_uuid)
        if not result:
            return _build_cors_response(make_response(jsonify({'error': 'Thread not found'}), 404))
        return _build_cors_response(jsonify({'ok': True, **result}))
    except ValueError as ve:
        msg = str(ve)
        if 'permanently deleted' in msg.lower():
            return _build_cors_response(make_response(jsonify({'error': msg}), 410))
        elif 'Max active' in msg:
            usage = get_usage_stats(user_id, plan)
            return _build_cors_response(make_response(jsonify({
                'error': msg,
                'usage': {
                    'active_threads': usage['active_threads'],
                    'threads_limit': limits.get('conversation_threads')
                }
            }), 403))
        return _build_cors_response(make_response(jsonify({'error': msg}), 400))
    except Exception as e:
        logger.error('chat_threads_restore error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread restore failed'}), 500))

@app.route('/api/chat/threads/usage', methods=['GET'])
@login_required
def chat_threads_usage():
    """10. Get comprehensive usage statistics."""
    try:
        from utils.thread_manager import get_usage_overview
        from plan_utils import get_plan_limits
    except Exception as e:
        logger.error('thread_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Thread system unavailable'}), 500))
    
    email = get_logged_in_email()
    limits = get_plan_limits(email)
    plan = limits['plan']
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User missing'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    try:
        result = get_usage_overview(user_id, plan)
        return _build_cors_response(jsonify({'ok': True, **result}))
    except Exception as e:
        logger.error('chat_threads_usage error: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Usage stats failed'}), 500))

# -------------------------------------------------------------------
# Travel Risk Itinerary Endpoints
# -------------------------------------------------------------------

@app.route('/api/travel-risk/itinerary', methods=['POST', 'OPTIONS'])
@login_required
def create_travel_itinerary():
    """Create a new travel itinerary with route risk analysis."""
    if request.method == 'OPTIONS':
        return _build_cors_response(make_response("", 204))
    
    try:
        from utils.itinerary_manager import create_itinerary
    except Exception as e:
        logger.error('itinerary_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Itinerary system unavailable'}), 500))
    
    email = get_logged_in_email()
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User not found'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    data = request.json or {}
    
    # Validate required fields
    if 'data' not in data:
        return _build_cors_response(make_response(jsonify({'error': 'Missing required field: data'}), 400))
    
    itinerary_data = data.get('data')
    title = data.get('title')
    description = data.get('description')
    alerts_raw = data.get('alerts_config')

    # Resolve plan for tier gating
    try:
        from plan_utils import get_plan_limits
        limits_info = get_plan_limits(email) or {}
        user_plan = (limits_info.get('plan') or os.getenv('DEFAULT_PLAN', 'FREE')).strip().upper()
    except Exception:
        user_plan = os.getenv('DEFAULT_PLAN', 'FREE').strip().upper()

    # Validate alerts_config if provided
    alerts_config = None
    if alerts_raw is not None:
        try:
            from alerts_config_utils import validate_alerts_config
            alerts_config = validate_alerts_config(alerts_raw, user_plan)
        except ValueError as ve:
            return _build_cors_response(make_response(jsonify({'ok': False, 'error': str(ve), 'code': 'VALIDATION_ERROR'}), 400))
        except Exception as e:
            logger.warning(f"alerts_config validation failed: {e}")
            alerts_config = None
    
    try:
        result = create_itinerary(
            user_id=user_id,
            data=itinerary_data,
            title=title,
            description=description,
            alerts_config=alerts_config
        )
        
        logger.info(f"Itinerary created: {result['itinerary_uuid']} by {email}")
        
        # Standardized envelope response
        response = make_response(jsonify({'ok': True, 'data': result}), 201)
        
        # Add ETag and version headers
        etag = f"\"itinerary/{result['itinerary_uuid']}/v{result['version']}\""
        response.headers['ETag'] = etag
        response.headers['X-Version'] = str(result['version'])
        response.headers['Last-Modified'] = result['updated_at']
        
        return _build_cors_response(response)
    except ValueError as ve:
        return _build_cors_response(make_response(jsonify({'error': str(ve)}), 400))
    except Exception as e:
        logger.error(f'create_travel_itinerary error: {e}')
        return _build_cors_response(make_response(jsonify({'error': 'Failed to create itinerary'}), 500))


@app.route('/api/travel-risk/itinerary', methods=['GET'])
@login_required
def list_travel_itineraries():
    """List user's travel itineraries with pagination."""
    try:
        from utils.itinerary_manager import list_itineraries
    except Exception as e:
        logger.error('itinerary_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Itinerary system unavailable'}), 500))
    
    email = get_logged_in_email()
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User not found'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    # Parse query params
    limit = int(request.args.get('limit', 20))
    offset = int(request.args.get('offset', 0))
    include_deleted = request.args.get('include_deleted', 'false').lower() == 'true'
    
    try:
        results = list_itineraries(
            user_id=user_id,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted
        )
        
        # Get total count for pagination
        from utils.itinerary_manager import get_itinerary_stats
        stats = get_itinerary_stats(user_id)
        total = stats['active'] if not include_deleted else stats['count']
        
        # Calculate pagination metadata
        has_next = (offset + len(results)) < total
        next_offset = offset + limit if has_next else None
        
        # Standardized envelope with pagination
        response_data = {
            'ok': True,
            'data': {
                'items': results,
                'count': len(results),
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_next': has_next,
                'next_offset': next_offset
            }
        }
        
        response = make_response(jsonify(response_data))
        response.headers['Cache-Control'] = 'private, max-age=15'
        
        return _build_cors_response(response)
    except Exception as e:
        logger.error(f'list_travel_itineraries error: {e}')
        return _build_cors_response(make_response(jsonify({'error': 'Failed to list itineraries'}), 500))


@app.route('/api/travel-risk/itinerary/<itinerary_uuid>', methods=['GET'])
@login_required
def get_travel_itinerary(itinerary_uuid):
    """Get a specific travel itinerary by UUID."""
    try:
        from utils.itinerary_manager import get_itinerary
    except Exception as e:
        logger.error('itinerary_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Itinerary system unavailable'}), 500))
    
    email = get_logged_in_email()
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User not found'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    try:
        result = get_itinerary(user_id=user_id, itinerary_uuid=itinerary_uuid)
        
        if not result:
            return _build_cors_response(make_response(jsonify({
                'ok': False,
                'error': 'Not found',
                'code': 'NOT_FOUND'
            }), 404))
        
        # Check If-None-Match for conditional GET (304)
        client_etag = request.headers.get('If-None-Match')
        server_etag = f"\"itinerary/{result['itinerary_uuid']}/v{result['version']}\""
        
        if client_etag == server_etag:
            return _build_cors_response(make_response('', 304))
        
        # Standardized envelope
        response = make_response(jsonify({'ok': True, 'data': result}))
        
        # Add headers
        response.headers['ETag'] = server_etag
        response.headers['X-Version'] = str(result['version'])
        response.headers['Last-Modified'] = result['updated_at']
        response.headers['Cache-Control'] = 'private, max-age=30'
        
        return _build_cors_response(response)
    except Exception as e:
        logger.error(f'get_travel_itinerary error: {e}')
        return _build_cors_response(make_response(jsonify({'error': 'Failed to get itinerary'}), 500))


@app.route('/api/travel-risk/itinerary/<itinerary_uuid>', methods=['PATCH'])
@login_required
def update_travel_itinerary(itinerary_uuid):
    """Update a travel itinerary with optimistic locking support."""
    try:
        from utils.itinerary_manager import update_itinerary
    except Exception as e:
        logger.error('itinerary_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Itinerary system unavailable'}), 500))
    
    email = get_logged_in_email()
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User not found'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    data = request.json or {}
    expected_version = data.get('version')  # For conflict detection
    alerts_raw = data.get('alerts_config')

    # Resolve plan
    try:
        from plan_utils import get_plan_limits
        limits_info = get_plan_limits(email) or {}
        user_plan = (limits_info.get('plan') or os.getenv('DEFAULT_PLAN', 'FREE')).strip().upper()
    except Exception:
        user_plan = os.getenv('DEFAULT_PLAN', 'FREE').strip().upper()

    alerts_config = None
    if alerts_raw is not None:
        try:
            from alerts_config_utils import validate_alerts_config
            alerts_config = validate_alerts_config(alerts_raw, user_plan)
        except ValueError as ve:
            return _build_cors_response(make_response(jsonify({'ok': False, 'error': str(ve), 'code': 'VALIDATION_ERROR'}), 400))
        except Exception as e:
            logger.warning(f"alerts_config validation failed: {e}")
            alerts_config = None
    
    # Check If-Match header (ETag-based concurrency)
    if_match = request.headers.get('If-Match')
    
    # Get current version for validation
    current = get_itinerary(user_id, itinerary_uuid)
    if not current:
        return _build_cors_response(make_response(jsonify({
            'ok': False,
            'error': 'Not found',
            'code': 'NOT_FOUND'
        }), 404))
    
    # Validate If-Match if provided (takes precedence over version)
    if if_match:
        server_etag = f"\"itinerary/{itinerary_uuid}/v{current['version']}\""
        if if_match != server_etag:
            return _build_cors_response(make_response(jsonify({
                'ok': False,
                'error': 'Precondition failed',
                'code': 'PRECONDITION_FAILED',
                'expected_etag': if_match,
                'current_etag': server_etag,
                'current_version': current['version']
            }), 412))
    
    try:
        result = update_itinerary(
            user_id=user_id,
            itinerary_uuid=itinerary_uuid,
            data=data.get('data'),
            title=data.get('title'),
            description=data.get('description'),
            expected_version=expected_version,
            alerts_config=alerts_config
        )
        
        if not result:
            return _build_cors_response(make_response(jsonify({
                'ok': False,
                'error': 'Not found',
                'code': 'NOT_FOUND'
            }), 404))
        
        logger.info(f"Itinerary updated: {itinerary_uuid} by {email} (v{result['version']})")
        
        # Standardized envelope
        response = make_response(jsonify({'ok': True, 'data': result}))
        
        # Add updated headers
        etag = f"\"itinerary/{result['itinerary_uuid']}/v{result['version']}\""
        response.headers['ETag'] = etag
        response.headers['X-Version'] = str(result['version'])
        response.headers['Last-Modified'] = result['updated_at']
        
        return _build_cors_response(response)
    except ValueError as ve:
        # Version conflict (409)
        if 'Version conflict' in str(ve):
            return _build_cors_response(make_response(jsonify({
                'ok': False,
                'error': str(ve),
                'code': 'VERSION_CONFLICT',
                'expected_version': expected_version,
                'current_version': current['version'],
                'id': itinerary_uuid
            }), 409))
        return _build_cors_response(make_response(jsonify({
            'ok': False,
            'error': str(ve),
            'code': 'VALIDATION_ERROR'
        }), 400))
    except Exception as e:
        logger.error(f'update_travel_itinerary error: {e}')
        return _build_cors_response(make_response(jsonify({'error': 'Failed to update itinerary'}), 500))


@app.route('/api/travel-risk/itinerary/<itinerary_uuid>', methods=['DELETE'])
@login_required
def delete_travel_itinerary(itinerary_uuid):
    """Delete a travel itinerary (soft delete by default)."""
    try:
        from utils.itinerary_manager import delete_itinerary
    except Exception as e:
        logger.error('itinerary_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Itinerary system unavailable'}), 500))
    
    email = get_logged_in_email()
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User not found'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    # Check for permanent delete flag
    permanent = request.args.get('permanent', 'false').lower() == 'true'
    
    # Check If-Match header
    if_match = request.headers.get('If-Match')
    if if_match:
        current = get_itinerary(user_id, itinerary_uuid)
        if current:
            server_etag = f"\"itinerary/{itinerary_uuid}/v{current['version']}\""
            if if_match != server_etag:
                return _build_cors_response(make_response(jsonify({
                    'ok': False,
                    'error': 'Precondition failed',
                    'code': 'PRECONDITION_FAILED'
                }), 412))
    
    try:
        deleted = delete_itinerary(
            user_id=user_id,
            itinerary_uuid=itinerary_uuid,
            soft=not permanent
        )
        
        if not deleted:
            return _build_cors_response(make_response(jsonify({
                'ok': False,
                'error': 'Not found',
                'code': 'NOT_FOUND'
            }), 404))
        
        logger.info(f"Itinerary {'permanently ' if permanent else ''}deleted: {itinerary_uuid} by {email}")
        return _build_cors_response(jsonify({
            'ok': True,
            'data': {'deleted': True, 'permanent': permanent}
        }))
    except Exception as e:
        logger.error(f'delete_travel_itinerary error: {e}')
        return _build_cors_response(make_response(jsonify({'error': 'Failed to delete itinerary'}), 500))


@app.route('/api/travel-risk/itinerary/stats', methods=['GET'])
@login_required
def get_itinerary_stats():
    """Get statistics about user's itineraries."""
    try:
        from utils.itinerary_manager import get_itinerary_stats
    except Exception as e:
        logger.error('itinerary_manager import failed: %s', e)
        return _build_cors_response(make_response(jsonify({'error': 'Itinerary system unavailable'}), 500))
    
    email = get_logged_in_email()
    
    if fetch_one is None:
        return _build_cors_response(make_response(jsonify({'error': 'DB unavailable'}), 503))
    
    user_row = fetch_one('SELECT id FROM users WHERE email=%s', (email,))
    if not user_row:
        return _build_cors_response(make_response(jsonify({'error': 'User not found'}), 404))
    user_id = user_row['id'] if isinstance(user_row, dict) else user_row[0]
    
    try:
        stats = get_itinerary_stats(user_id=user_id)
        
        # Standardized envelope
        return _build_cors_response(jsonify({
            'ok': True,
            'data': {
                'total': stats['count'],
                'active': stats['active'],
                'deleted': stats['deleted']
            }
        }))
    except Exception as e:
        logger.error(f'get_itinerary_stats error: {e}')
        return _build_cors_response(make_response(jsonify({'error': 'Failed to get stats'}), 500))

# -------------------------------------------------------------------
# Local development entrypoint
# -------------------------------------------------------------------
if __name__ == "__main__":
    import os
    print("[Sentinel AI] Starting local development server...")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)