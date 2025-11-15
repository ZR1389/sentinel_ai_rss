
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

from flask import Flask, request, jsonify, make_response, g

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

# ---------- Global Error Handlers ----------
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
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-User-Email, Authorization"
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
        plan = payload.get("plan")
        # Optional: usage — placeholder until metering store is added
        usage = {}
        return _build_cors_response(jsonify({
            "email": email,
            "plan": plan,
            "email_verified": True,  # assume verified if access token exists in our flow
            "usage": usage,
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
CHAT_QUERY_MAX_CHARS = int(os.getenv("CHAT_QUERY_MAX_CHARS", "5000"))

# SOCMINT rates (platform-specific)
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

    # --- NEW: Attach usage ---
    try:
        # This function must return a dict, e.g. {'chat_messages_used': 2}
        from plan_utils import get_usage
        usage = get_usage(email) if get_usage else None
        if usage:
            data["usage"] = usage
    except Exception:
        data["usage"] = {}  

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
                return _build_cors_response(make_response(jsonify({"error": msg, "quota_exceeded": True}), 429))
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
        
        success_response = {
            "accepted": True,
            "session_id": session_id,
            "message": "Processing your request. Poll /api/chat/status/<session_id> for results.",
            "plan": get_plan(email) if get_plan else "FREE",
            "quota": {
                "plan": get_plan(email) if get_plan else "FREE",
                "background_processing": True
            }
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
    # Paid gate (consistent with /alerts)
    if require_paid_feature is None:
        return _build_cors_response(make_response(jsonify({"error": "Plan gate unavailable"}), 503))
    email = get_logged_in_email()
    ok, msg = require_paid_feature(email)
    if not ok:
        return _build_cors_response(make_response(jsonify({"error": msg}), 403))

    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))

    # Cap limit defensively
    try:
        limit = int(request.args.get("limit", 20))
    except Exception:
        limit = 20
    limit = max(1, min(limit, 500))

    region = request.args.get("region")
    country = request.args.get("country")
    city = request.args.get("city")

    where = []
    params = []
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
        return _build_cors_response(jsonify({"ok": True, "items": rows}))
    except Exception as e:
        logger.error("alerts_latest error: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Query failed"}), 500))

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
        radius_km = int(data.get('radius_km', 100))
        days = int(data.get('days', 14))
        output_format = str(data.get('format', 'structured')).lower()

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

        return _build_cors_response(jsonify({
            'assessment': assessment,
            'advisory': advisory_text,
            'format': output_format,
        }))
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

# -------------------------------------------------------------------
# Local development entrypoint
# -------------------------------------------------------------------
if __name__ == "__main__":
    import os
    print("[Sentinel AI] Starting local development server...")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)