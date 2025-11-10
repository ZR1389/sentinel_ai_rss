# main.py — Sentinel AI App API (JWT-guarded) • v2025-08-13
# Notes:
# - Only /chat counts toward plan usage, and only AFTER a successful advisory.
# - /rss/run and /engine/run are backend ops and are NOT metered.
# - Newsletter is UNMETERED; requires verified login.
# - PDF/Email/Push/Telegram are UNMETERED but require a PAID plan.
# - Auth/verification endpoints added and left unmetered.
# - Profile endpoints added: /profile/me (GET), /profile/update (POST).

from __future__ import annotations
import os
import logging
import traceback
import base64
from typing import Any, Dict, Optional
from datetime import datetime

from flask import Flask, request, jsonify, make_response

from map_api import map_api
from webpush_endpoints import webpush_bp

app = Flask(__name__)
app.register_blueprint(map_api)
app.register_blueprint(webpush_bp)

# ---------- Logging ----------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sentinel.main")

# ---------- Optional CORS (simple) ----------
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")

def _build_cors_response(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS
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

# ---------- Optional psycopg2 fallback for Telegram linking ----------
DATABASE_URL = os.getenv("DATABASE_URL")
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

@app.route("/auth/status", methods=["GET", "OPTIONS"])
def auth_status():
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    
    # Try to get email from JWT token first
    auth_header = request.headers.get("Authorization", "")
    email = None

    if auth_header.startswith("Bearer "):
        try:
           from auth_utils import decode_token
           token = auth_header.split(" ", 1)[1].strip()
           payload = decode_token(token)
           if payload and payload.get("type") == "access":
               email = payload.get("user_email")
        except Exception as e:
            logger.warning("JWT decode failed in auth_status: %s", e)

    # Fallback to old headers (for compatibility)
    if not email:
        email = request.headers.get("X-User-Email") or request.args.get("email") or ""
        email = email.strip().lower()

    if not email:
        return _build_cors_response(make_response(jsonify({"error": "Missing or invalid token"}), 401))
    
    verified = _is_verified(email)
    plan_name = "FREE"
    if get_plan:
        try:
            p = get_plan(email)
            if isinstance(p, str) and p:
                plan_name = p.upper()
        except Exception:
            pass
    
    # Get usage info + enforce plan-based limits
    usage_data = {"chat_messages_used": 0, "chat_messages_limit": 3}
    try:
       from plan_utils import get_usage, get_plan_limits
       u = get_usage(email)
       if isinstance(u, dict):
          usage_data["chat_messages_used"] = u.get("chat_messages_used", 0)

       # Always determine plan limits explicitly
       if plan_name == "PRO":
           usage_data["chat_messages_limit"] = 1000
       elif plan_name in ("VIP", "ENTERPRISE"):
           usage_data["chat_messages_limit"] = 5000
       else:
           # fallback to default or plan_utils-based
           try:
              limits = get_plan_limits(email) or {}
              usage_data["chat_messages_limit"] = limits.get("chat_messages_per_month", 3)
           except Exception:
              usage_data["chat_messages_limit"] = 3

    except Exception as e:
        logger.warning("Failed to get usage in auth_status: %s", e)

    return _build_cors_response(jsonify({
        "ok": True, 
        "email": email,
        "email_verified": bool(verified), 
        "plan": plan_name,
        "usage": usage_data
    }))

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
@app.route("/chat", methods=["POST", "OPTIONS"])
def chat_options():
    # keep preflight separate to preserve decorator behavior below
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _chat_impl()

@app.route("/chat", methods=["POST"])
@login_required
def _chat_impl():
    import signal
    import time
    
    # Set a timeout for the entire chat request (4 minutes)
    def timeout_handler(signum, frame):
        raise TimeoutError("Chat request timed out")
    
    # Only set signal handler on Unix systems
    if hasattr(signal, 'SIGALRM'):
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(240)  # 4 minutes
    
    start_time = time.time()
    
    try:
        payload = _json_request()
        query = (payload.get("query") or "").strip()
        profile_data = payload.get("profile_data") or {}
        input_data = payload.get("input_data") or {}
        email = get_logged_in_email()  # from JWT

        if not query:
            return _build_cors_response(make_response(jsonify({"error": "Missing 'query'"}), 400))
        if _advisor_callable is None:
            return _build_cors_response(make_response(jsonify({"error": "Advisor unavailable"}), 503))

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

        # ----- Call Advisor (do not increment yet) -----
        try:
            result = _advisor_call(query=query, email=email, profile_data=profile_data, input_data=input_data)
        except TimeoutError:
            logger.error("Advisor call timed out after %s seconds", time.time() - start_time)
            return _build_cors_response(make_response(jsonify({
                "error": "Request timeout. Please try a shorter query or try again later.",
                "timeout": True
            }), 504))
        except Exception as e:
            logger.error("advisor error: %s\n%s", e, traceback.format_exc())
            return _build_cors_response(make_response(jsonify({"error": "Advisor failed"}), 502))

        # ----- Increment usage ON SUCCESS only -----
        try:
            if increment_user_message_usage:
                increment_user_message_usage(email)
        except Exception as e:
            logger.error("usage increment failed: %s", e)

        return _build_cors_response(jsonify(result))
    
    except TimeoutError:
        logger.error("Chat request timed out after %s seconds", time.time() - start_time)
        return _build_cors_response(make_response(jsonify({
            "error": "Request timeout. Please try a shorter query or try again later.",
            "timeout": True
        }), 504))
    finally:
        # Clear the alarm
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)

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
          tags, early_warning_indicators
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
          tags
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
    query = payload.get("query", "").strip()
    context = payload.get("context", "")
    
    if not query:
        return _build_cors_response(make_response(jsonify({"error": "Query required"}), 400))

    if len(query) > 500:
        return _build_cors_response(make_response(jsonify({"error": "Query too long (max 500 chars)"}), 400))

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
        result, model_used = route_llm_batch(alerts_batch)
        
        return _build_cors_response(jsonify({
            "ok": True,
            "alerts_processed": len(alerts_batch),
            "model": model_used,
            "enrichment_result": result[:500] + "..." if len(result) > 500 else result,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }))
        
    except Exception as e:
        logger.error("batch_enrich_alerts error: %s\n%s", e, traceback.format_exc())
        return _build_cors_response(make_response(jsonify({"error": "Batch enrichment failed"}), 500))

# ---------- Entrypoint ----------
if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    debug = bool(os.getenv("FLASK_DEBUG", "").lower() in ("1","true","yes","y"))
    logger.info("Starting Sentinel AI API on %s:%s (debug=%s)", host, port, debug)
    app.run(host=host, port=port, debug=debug)