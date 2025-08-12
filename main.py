import os
import logging
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from werkzeug.exceptions import BadRequest, MethodNotAllowed, UnsupportedMediaType

from security_log_utils import log_security_event

# Import marshmallow schemas
from schemas import RegisterSchema, ResetPasswordSchema, ProfileSchema, ChatSchema

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from chat_handler import handle_user_query
from email_dispatcher import generate_pdf
from plan_utils import (
    get_plan_limits, get_usage, ensure_user_exists,
    check_user_message_quota, fetch_user_profile,
    check_user_pdf_quota, increment_user_pdf_usage
)
from newsletter import subscribe_to_newsletter
from verification_utils import (
    send_code_email, check_verification_code,
    get_client_ip, email_verification_ip_quota_exceeded,
    log_email_verification_ip
)
from auth_utils import (
    login_required, get_logged_in_email, create_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2

from password_strength_utils import is_strong_password

import threading
import time
import json
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

load_dotenv()
RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

if not os.getenv("DATABASE_URL"):
    log.warning("DATABASE_URL not set! Database operations may fail.")
if not os.getenv("PORT"):
    log.info("PORT not set, using default 8080.")

PORT = int(os.getenv("PORT", 8080))

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_secret_please_change")

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.getenv("REDIS_URL", "memory://"),
)
ALLOWED_ORIGINS = [
    "https://zikarisk.com",
    "http://zikarisk.com",
    "https://www.zikarisk.com",
    "http://www.zikarisk.com"
]
CORS(
    app,
    resources={r"/*": {"origins": ALLOWED_ORIGINS}},
    supports_credentials=True,
    allow_headers=["Authorization", "Content-Type"]
)
app.config['SESSION_COOKIE_SAMESITE'] = "None"
app.config['SESSION_COOKIE_SECURE'] = True

def _build_cors_response(response=None):
    req_origin = request.headers.get("Origin")
    headers = {
        "Access-Control-Allow-Methods": "POST, OPTIONS, GET, PATCH, PUT, DELETE",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Allow-Credentials": "true"
    }
    if req_origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = req_origin
    else:
        headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS[0]
    if response is None:
        response = jsonify({})
    response.headers.update(headers)
    return response

@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        resp = make_response()
        resp.status_code = 200
        req_origin = request.headers.get("Origin")
        headers = {
            "Access-Control-Allow-Methods": "POST, OPTIONS, GET, PATCH, PUT, DELETE",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Credentials": "true"
        }
        if req_origin in ALLOWED_ORIGINS:
            headers["Access-Control-Allow-Origin"] = req_origin
        else:
            headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS[0]
        for k, v in headers.items():
            resp.headers[k] = v
        return resp

def require_plan_feature(email, feature):
    plan_limits = get_plan_limits(email)
    if not plan_limits.get(feature):
        return False
    return True

def is_pro_or_enterprise(email):
    plan_limits = get_plan_limits(email)
    plan_name = plan_limits.get("name", "FREE")
    return plan_name in ["PRO", "Enterprise"]

# --- USER PREFERENCES ENDPOINTS ---
@app.route("/set_preferences", methods=["POST"])
@login_required
def set_preferences():
    email = get_logged_in_email()
    data = request.get_json(force=True)
    watchlist = data.get("country_watchlist")
    categories = data.get("threat_categories")
    channels = data.get("alert_channels")
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_profiles (email, country_watchlist, threat_categories, alert_channels)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET
                        country_watchlist=EXCLUDED.country_watchlist,
                        threat_categories=EXCLUDED.threat_categories,
                        alert_channels=EXCLUDED.alert_channels
                """, (
                    email,
                    watchlist,
                    categories,
                    channels
                ))
                conn.commit()
        return _build_cors_response(jsonify({"success": True, "message": "Preferences updated."}))
    except Exception as e:
        log.error(f"Set preferences error: {e}")
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/get_preferences", methods=["GET"])
@login_required
def get_preferences():
    email = get_logged_in_email()
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT country_watchlist, threat_categories, alert_channels
                    FROM user_profiles WHERE email = %s
                """, (email,))
                row = cur.fetchone()
                if not row:
                    return _build_cors_response(jsonify({
                        "country_watchlist": None,
                        "threat_categories": None,
                        "alert_channels": None
                    }))
                result = {
                    "country_watchlist": row[0],
                    "threat_categories": row[1],
                    "alert_channels": row[2]
                }
        return _build_cors_response(jsonify(result))
    except Exception as e:
        log.error(f"Get preferences error: {e}")
        return _build_cors_response(jsonify({"error": str(e)})), 500

# --- PUSH NOTIFICATIONS ENDPOINT ---
SUBSCRIBERS_FILE = Path("subscribers.json")

def save_subscription(subscription, email):
    # Load existing
    if SUBSCRIBERS_FILE.exists():
        with SUBSCRIBERS_FILE.open("r", encoding="utf-8") as f:
            subs = json.load(f)
    else:
        subs = []
    # Remove any previous subscription for this email
    subs = [sub for sub in subs if sub.get("email") != email]
    # Add new
    subscription["email"] = email
    subs.append(subscription)
    with SUBSCRIBERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(subs, f, indent=2)

@app.route("/subscribe_push", methods=["POST"])
@login_required
def subscribe_push():
    data = request.get_json(force=True)
    subscription = data.get("subscription")
    email = get_logged_in_email()
    save_subscription(subscription, email)
    log_security_event("push_subscribe", email=email, ip=get_remote_address(), endpoint="/subscribe_push")
    return jsonify({"success": True})

@app.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    data = request.get_json(force=True)
    errors = RegisterSchema().validate(data)
    if errors:
        return _build_cors_response(jsonify({"success": False, "error": errors})), 400
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    ip = get_remote_address()
    if not email or not password or not is_strong_password(password):
        log_security_event("register_failed", email=email, ip=ip, endpoint="/register", details="Missing email or password or weak password")
        return _build_cors_response(jsonify({"success": False, "error": "Missing email or password, or password does not meet security requirements"})), 400
    hashed = generate_password_hash(password)
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM users WHERE email = %s", (email,))
                if cur.fetchone():
                    log_security_event("register_failed", email=email, ip=ip, endpoint="/register", details="Email already registered")
                    return _build_cors_response(jsonify({"success": False, "error": "Email already registered. Please log in or reset password."})), 409
                cur.execute(
                    "INSERT INTO users (email, password_hash, plan, email_verified) VALUES (%s, %s, %s, %s)",
                    (email, hashed, "FREE", False)
                )
                conn.commit()
        ok, error = send_code_email(email)
        if not ok:
            log_security_event("register_email_failure", email=email, ip=ip, endpoint="/register", details=error or "Failed to send verification email")
            return _build_cors_response(jsonify({"success": False, "error": error or "Failed to send verification email"})), 500
        log_security_event("register_success", email=email, ip=ip, endpoint="/register")
        return _build_cors_response(jsonify({"success": True, "message": "Registration successful. Please check your email for the verification code."}))
    except Exception as e:
        log_security_event("register_error", email=email, ip=ip, endpoint="/register", details=str(e))
        log.error(f"Registration error: {e}")
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    ip = get_remote_address()
    if not email or not password:
        log_security_event("login_failed", email=email, ip=ip, endpoint="/login", details="Missing email or password")
        return _build_cors_response(jsonify({"success": False, "error": "Missing email or password"})), 400
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash, email_verified FROM users WHERE email=%s", (email,))
                row = cur.fetchone()
                if not row:
                    log_security_event("login_failed", email=email, ip=ip, endpoint="/login", details="Invalid credentials")
                    return _build_cors_response(jsonify({"success": False, "error": "Invalid credentials"})), 401
                hashed, email_verified = row
                if not hashed:
                    log_security_event("login_failed", email=email, ip=ip, endpoint="/login", details="No password set")
                    return _build_cors_response(jsonify({"success": False, "error": "No password set for this account. Please use 'Forgot password' to set a password."})), 403
                if not check_password_hash(hashed, password):
                    log_security_event("login_failed", email=email, ip=ip, endpoint="/login", details="Invalid credentials")
                    return _build_cors_response(jsonify({"success": False, "error": "Invalid credentials"})), 401
                if not email_verified:
                    log_security_event("login_failed", email=email, ip=ip, endpoint="/login", details="Email not verified")
                    return _build_cors_response(jsonify({"success": False, "error": "Email not verified"})), 403
        token = create_jwt(email)
        log_security_event("login_success", email=email, ip=ip, endpoint="/login")
        return _build_cors_response(jsonify({"success": True, "token": token}))
    except Exception as e:
        log_security_event("login_error", email=email, ip=ip, endpoint="/login", details=str(e))
        log.error(f"Login error: {e}")
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/request_password_reset", methods=["POST"])
@limiter.limit("3 per hour", key_func=lambda: request.get_json(force=True).get("email", get_remote_address()))
def request_password_reset():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    ip = get_remote_address()
    if not email:
        log_security_event("password_reset_failed", email=email, ip=ip, endpoint="/request_password_reset", details="Missing email")
        return _build_cors_response(jsonify({"success": False, "error": "Missing email"})), 400
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM users WHERE email=%s", (email,))
                if not cur.fetchone():
                    log_security_event("password_reset_failed", email=email, ip=ip, endpoint="/request_password_reset", details="No such user")
                    return _build_cors_response(jsonify({"success": False, "error": "No such user"})), 404
                code = f"{random.randint(100000, 999999)}"
                expiry = datetime.utcnow() + timedelta(minutes=15)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS password_resets (
                        email TEXT PRIMARY KEY,
                        code TEXT,
                        expires_at TIMESTAMP
                    );
                """)
                cur.execute("""
                    INSERT INTO password_resets (email, code, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET code=%s, expires_at=%s
                """, (email, code, expiry, code, expiry))
                conn.commit()
        send_code_email(email, code, subject="Your Sentinel AI password reset code")
        log_security_event("password_reset_requested", email=email, ip=ip, endpoint="/request_password_reset")
        return _build_cors_response(jsonify({"success": True}))
    except Exception as e:
        log_security_event("password_reset_error", email=email, ip=ip, endpoint="/request_password_reset", details=str(e))
        log.error(f"Password reset request error: {e}")
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/reset_password", methods=["POST"])
@limiter.limit("5 per hour", key_func=lambda: request.get_json(force=True).get("email", get_remote_address()))
def reset_password():
    data = request.get_json(force=True)
    errors = ResetPasswordSchema().validate(data)
    if errors:
        return _build_cors_response(jsonify({"success": False, "error": errors})), 400
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()
    new_password = data.get("new_password", "")
    ip = get_remote_address()
    if not (email and code and new_password) or not is_strong_password(new_password):
        log_security_event("reset_password_failed", email=email, ip=ip, endpoint="/reset_password", details="Missing fields or weak password")
        return _build_cors_response(jsonify({"success": False, "error": "Missing fields or password does not meet security requirements"})), 400
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT code, expires_at FROM password_resets WHERE email=%s", (email,))
                row = cur.fetchone()
                if not row:
                    log_security_event("reset_password_failed", email=email, ip=ip, endpoint="/reset_password", details="No reset request")
                    return _build_cors_response(jsonify({"success": False, "error": "No reset request"})), 400
                db_code, expires_at = row
                if expires_at < datetime.utcnow():
                    log_security_event("reset_password_failed", email=email, ip=ip, endpoint="/reset_password", details="Code expired")
                    return _build_cors_response(jsonify({"success": False, "error": "Code expired"})), 400
                if db_code != code:
                    log_security_event("reset_password_failed", email=email, ip=ip, endpoint="/reset_password", details="Incorrect code")
                    return _build_cors_response(jsonify({"success": False, "error": "Incorrect code"})), 400
                hashed = generate_password_hash(new_password)
                cur.execute("UPDATE users SET password_hash=%s, email_verified=TRUE WHERE email=%s", (hashed, email))
                cur.execute("DELETE FROM password_resets WHERE email=%s", (email,))
                conn.commit()
        log_security_event("reset_password_success", email=email, ip=ip, endpoint="/reset_password")
        return _build_cors_response(jsonify({"success": True}))
    except Exception as e:
        log_security_event("reset_password_error", email=email, ip=ip, endpoint="/reset_password", details=str(e))
        log.error(f"Password reset error: {e}")
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    log_security_event("logout", email=get_logged_in_email(), ip=get_remote_address(), endpoint="/logout")
    return _build_cors_response(jsonify({"success": True}))

@app.route("/profile", methods=["GET"])
@login_required
def get_profile():
    email = get_logged_in_email()
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT profession, employer, destination, travel_start, travel_end, means_of_transportation, reason_for_travel, custom_fields FROM user_profiles WHERE email = %s", (email,))
                row = cur.fetchone()
                keys = ["profession", "employer", "destination", "travel_start", "travel_end", "means_of_transportation", "reason_for_travel", "custom_fields"]
                if not row:
                    return _build_cors_response(jsonify({key: None for key in keys}))
                profile_dict = dict(zip(keys, row))
                for k in keys:
                    if k not in profile_dict or profile_dict[k] is None:
                        profile_dict[k] = None
        return _build_cors_response(jsonify(profile_dict))
    except Exception as e:
        log.error(f"Profile GET error: {e}")
        return _build_cors_response(jsonify({"error": str(e)})), 500

@app.route("/profile", methods=["POST", "PATCH"])
@login_required
def update_profile():
    email = get_logged_in_email()
    data = request.get_json(force=True)
    errors = ProfileSchema().validate(data)
    if errors:
        return _build_cors_response(jsonify({"success": False, "error": errors})), 400
    keys = [
        "profession", "employer", "destination", "travel_start",
        "travel_end", "means_of_transportation", "reason_for_travel", "custom_fields"
    ]
    values = [data.get(k, None) for k in keys]
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO user_profiles (email, {', '.join(keys)})
                    VALUES (%s, {', '.join(['%s']*len(keys))})
                    ON CONFLICT (email) DO UPDATE SET {', '.join([f"{k}=EXCLUDED.{k}" for k in keys])}
                """, [email] + values)
                conn.commit()
        return _build_cors_response(jsonify({"success": True}))
    except Exception as e:
        log.error(f"Profile update error: {e}")
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/update_profile", methods=["POST"])
@login_required
def update_profile_v2():
    """Update risk preferences, travel regions, and other user profile fields."""
    email = get_logged_in_email()
    data = request.get_json(force=True)
    # Accept flexible keys for advanced personalization
    allowed_keys = [
        "profession", "employer", "destination", "travel_start", "travel_end",
        "means_of_transportation", "reason_for_travel", "custom_fields", "risk_tolerance",
        "asset_type", "preferred_alert_types"
    ]
    values = [data.get(k, None) for k in allowed_keys]
    try:
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO user_profiles (email, {', '.join(allowed_keys)})
                    VALUES (%s, {', '.join(['%s']*len(allowed_keys))})
                    ON CONFLICT (email) DO UPDATE SET {', '.join([f"{k}=EXCLUDED.{k}" for k in allowed_keys])}
                """, [email] + values)
                conn.commit()
        return _build_cors_response(jsonify({"success": True}))
    except Exception as e:
        log.error(f"Profile update error: {e}")
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/chat", methods=["POST", "OPTIONS"])
@limiter.limit("20 per minute", key_func=lambda: get_logged_in_email() or get_remote_address())
@login_required
def chat():
    print("CHAT ENDPOINT HIT")
    if request.method == "OPTIONS":
        print("OPTIONS request received")
        return _build_cors_response()
    try:
        print("Parsing JSON...")
        data = request.get_json(force=True)
        print("DATA RECEIVED:", data)
        errors = ChatSchema().validate(data)
        print("SCHEMA ERRORS:", errors)
        if errors:
            return _build_cors_response(jsonify({"error": errors})), 400
        log.info("🔒 Incoming /chat request...")
        query = data.get("query", "")
        email = get_logged_in_email()
        region = data.get("region")
        threat_type = data.get("type")
        print(f"query={query}, email={email}, region={region}, threat_type={threat_type}")
        region = None if not region or str(region).lower() == "all" else str(region)
        threat_type = None if not threat_type or str(threat_type).lower() == "all" else str(threat_type)
        if email:
            print("Ensuring user exists...")
            ensure_user_exists(email, plan="FREE")
            plan_limits = get_plan_limits(email)
            ok, msg = check_user_message_quota(email, plan_limits)
            if not ok:
                log_security_event("quota_exceeded", email=email, ip=get_remote_address(), endpoint="/chat", plan=plan_limits.get("name"), details=f"Quota: {msg}")
                return _build_cors_response(jsonify({"error": msg, "quota_exceeded": True})), 429
            if not require_plan_feature(email, "insights") and region and threat_type:
                log_security_event("plan_denied", email=email, ip=get_remote_address(), endpoint="/chat", plan=plan_limits.get("name"), details="Advanced insights not available")
                return _build_cors_response(jsonify({"error": "Advanced insights are not available on your plan. Please upgrade."})), 403
        print("Calling handle_user_query...")
        trend_data_request = data.get("trend_data", False)
        requested_profile = data.get("profile", None)
        result = handle_user_query(
            {"query": query},
            email=email,
            region=region,
            threat_type=threat_type,
        )
        if trend_data_request:
            from db_utils import fetch_past_incidents
            historical = fetch_past_incidents(region=region, category=result.get("alerts", [{}])[0].get("category"), days=90, limit=100)
            from risk_shared import compute_trend_metrics
            trend_metrics = compute_trend_metrics(historical)
            result["trend_metrics"] = trend_metrics

        if requested_profile and isinstance(requested_profile, dict):
            result["requested_profile"] = requested_profile
            user_profile = fetch_user_profile(email)
            result["user_profile"] = user_profile

        print("handle_user_query returned, preparing response...")
        return _build_cors_response(jsonify(result))
    except BadRequest:
        print("BadRequest error")
        log_security_event("bad_request", email=get_logged_in_email(), ip=get_remote_address(), endpoint="/chat", details="Malformed input")
        return _build_cors_response(jsonify({"error": "Malformed input"})), 400
    except MethodNotAllowed:
        print("MethodNotAllowed error")
        log_security_event("method_not_allowed", email=get_logged_in_email(), ip=get_remote_address(), endpoint="/chat")
        return _build_cors_response(jsonify({"error": "Method not allowed"})), 405
    except UnsupportedMediaType:
        print("UnsupportedMediaType error")
        log_security_event("unsupported_media_type", email=get_logged_in_email(), ip=get_remote_address(), endpoint="/chat")
        return _build_cors_response(jsonify({"error": "Unsupported media type"})), 415
    except Exception as e:
        print(f"🔥 Unhandled error in /chat: {e}")
        log.error(f"🔥 Unhandled error in /chat: {e}")
        log_security_event("internal_error", email=get_logged_in_email(), ip=get_remote_address(), endpoint="/chat", details=str(e))
        return _build_cors_response(jsonify({"error": "Internal server error"})), 500

@app.route("/request_report", methods=["POST"])
@limiter.limit("3 per hour", key_func=lambda: get_logged_in_email() or get_remote_address())
@login_required
def request_report():
    print("REQUEST_REPORT ENDPOINT HIT")
    try:
        data = request.get_json(force=True)
        email = get_logged_in_email()
        plan_limits = get_plan_limits(email)
        plan_name = plan_limits.get("name", "FREE")

        # 1. Plan gating
        if plan_name not in ["PRO", "Enterprise"]:
            log_security_event(
                "plan_denied",
                email=email,
                ip=get_remote_address(),
                endpoint="/request_report",
                plan=plan_name,
                details="Report/briefing not available for this plan"
            )
            return _build_cors_response(jsonify({
                "error": "Briefings are only available to PRO or Enterprise users. Please upgrade your plan."
            })), 403

        # 2. Feature gating
        if not plan_limits.get("custom_pdf_briefings_frequency"):
            log_security_event("plan_denied", email=email, ip=get_remote_address(), endpoint="/request_report", plan=plan_name, details="PDF reports not available")
            return _build_cors_response(jsonify({"error": "Your plan does not allow PDF reports. Please upgrade for access."})), 403

        # 3. Quota check
        ok, quota_msg = check_user_pdf_quota(email, plan_limits)
        if not ok:
            log_security_event("pdf_quota_exceeded", email=email, ip=get_remote_address(), endpoint="/request_report", plan=plan_name, details=quota_msg)
            usage = get_usage(email)
            return _build_cors_response(jsonify({
                "error": quota_msg,
                "quota": {
                    "used": usage.get("pdf_reports_used", 0),
                    "limit": plan_limits.get("pdf_reports_per_month")
                }
            })), 429

        region = data.get("region")
        threat_type = data.get("type")
        region = None if not region or str(region).lower() == "all" else str(region)
        threat_type = None if not threat_type or str(threat_type).lower() == "all" else str(threat_type)

        ensure_user_exists(email, plan="FREE")
        alerts = handle_user_query(
            {"query": "Generate my report"},
            email=email,
            region=region,
            threat_type=threat_type
        ).get("alerts", [])

        generate_pdf(email, alerts, plan_name)
        increment_user_pdf_usage(email)  # <--- Increment quota on success!

        usage = get_usage(email)
        log_security_event("report_generated", email=email, ip=get_remote_address(), endpoint="/request_report", plan=plan_name, details=f"Alerts included: {len(alerts)}")
        return _build_cors_response(jsonify({
            "status": "Report generated and sent",
            "alerts_included": len(alerts),
            "quota": {
                "used": usage.get("pdf_reports_used", 0),
                "limit": plan_limits.get("pdf_reports_per_month")
            }
        }))
    except Exception as e:
        log.error(f"Report generation failed: {e}")
        log_security_event("report_error", email=get_logged_in_email(), ip=get_remote_address(), endpoint="/request_report", details=str(e))
        return _build_cors_response(jsonify({"error": "Internal server error"})), 500

@app.route("/send_telegram", methods=["POST"])
@limiter.limit("3 per hour", key_func=lambda: get_logged_in_email() or get_remote_address())
@login_required
def send_telegram():
    email = get_logged_in_email()
    plan_limits = get_plan_limits(email)
    if not require_plan_feature(email, "telegram"):
        log_security_event("plan_denied", email=email, ip=get_remote_address(), endpoint="/send_telegram", plan=plan_limits.get("name"), details="Telegram not available")
        return _build_cors_response(jsonify({"error": "Your plan does not allow Telegram alerts. Please upgrade for access."})), 403
    log_security_event("telegram_alert_sent", email=email, ip=get_remote_address(), endpoint="/send_telegram", plan=plan_limits.get("name"))
    return _build_cors_response(jsonify({"success": True, "message": "Telegram alert sent (stub)"}))

@app.route("/user_plan", methods=["GET"])
@login_required
def user_plan():
    print("USER_PLAN ENDPOINT HIT")
    email = get_logged_in_email()
    if email:
        ensure_user_exists(email, plan="FREE")
    plan_limits = get_plan_limits(email)
    features = {
        "pdf": bool(plan_limits.get("custom_pdf_briefings_frequency")),
        "insights": bool(plan_limits.get("insights")),
        "telegram": bool(plan_limits.get("telegram")),
        "alerts": bool(plan_limits.get("rss_monthly", 0) > 0),
        "newsletter": bool(plan_limits.get("newsletter")),
    }
    usage = get_usage(email)
    log_security_event("plan_query", email=email, ip=get_remote_address(), endpoint="/user_plan", plan=plan_limits.get("name"))
    return _build_cors_response(jsonify({
        "email": email,
        "plan": plan_limits.get("name", "FREE"),
        "features": features,
        "limits": plan_limits,
        "usage": usage,
    }))

@app.route("/plan_features", methods=["GET"])
def plan_features():
    print("PLAN_FEATURES ENDPOINT HIT")
    from plan_rules import PLAN_RULES
    return _build_cors_response(jsonify(PLAN_RULES))

@app.route("/usage", methods=["GET"])
@login_required
def usage():
    print("USAGE ENDPOINT HIT")
    email = get_logged_in_email()
    print(f"usage email={email}")
    if not email:
        log_security_event("usage_failed", email=email, ip=get_remote_address(), endpoint="/usage", details="Missing user_email")
        return _build_cors_response(jsonify({"error": "Missing user_email"})), 400
    if email:
        ensure_user_exists(email, plan="FREE")
    usage_data = get_usage(email)
    log_security_event("usage_query", email=email, ip=get_remote_address(), endpoint="/usage")
    return _build_cors_response(jsonify(usage_data))

@app.route("/health", methods=["GET"])
def health_check():
    print("HEALTH_CHECK ENDPOINT HIT")
    return _build_cors_response(jsonify({"status": "ok", "version": "1.0"})), 200

@app.route("/send_verification_code", methods=["POST"])
@limiter.limit("5 per hour", key_func=lambda: request.get_json(force=True).get("user_email", get_remote_address()))
def send_code_route():
    print("SEND_VERIFICATION_CODE ENDPOINT HIT")
    try:
        print("Parsing JSON for verification code...")
        data = request.get_json(force=True)
        email = data.get("user_email", "").strip().lower()
        print(f"send_verification_code email={email}")
        ip = get_client_ip(request)
        if not email:
            log_security_event("verification_failed", email=email, ip=ip, endpoint="/send_verification_code", details="Missing user_email")
            return _build_cors_response(jsonify({"success": False, "error": "Missing user_email"})), 400
        ensure_user_exists(email, plan="FREE")
        if email_verification_ip_quota_exceeded(ip):
            log_security_event("verification_ip_quota_exceeded", email=email, ip=ip, endpoint="/send_verification_code")
            return _build_cors_response(jsonify({"success": False, "error": "Too many verification attempts from your IP. Please try again later."})), 429
        log_email_verification_ip(ip)
        ok, error = send_code_email(email)
        if ok:
            log_security_event("verification_code_sent", email=email, ip=ip, endpoint="/send_verification_code")
            return _build_cors_response(jsonify({"success": True}))
        else:
            log_security_event("verification_code_failed", email=email, ip=ip, endpoint="/send_verification_code", details=error)
            return _build_cors_response(jsonify({"success": False, "error": error})), 403
    except Exception as e:
        log.error(f"Verification send failed: {e}")
        log_security_event("verification_code_error", email=None, ip=None, endpoint="/send_verification_code", details=str(e))
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/verify_code", methods=["POST"])
@limiter.limit("10 per hour", key_func=lambda: request.get_json(force=True).get("user_email", get_remote_address()))
def verify_code_route():
    print("VERIFY_CODE ENDPOINT HIT")
    try:
        print("Parsing JSON for verify code...")
        data = request.get_json(force=True)
        email = data.get("user_email", "").strip().lower()
        code = data.get("code", "").strip()
        ip = get_remote_address()
        print(f"verify_code email={email}, code={code}")
        if not email or not code:
            log_security_event("verify_code_failed", email=email, ip=ip, endpoint="/verify_code", details="Missing user_email or code")
            return _build_cors_response(jsonify({"success": False, "error": "Missing user_email or code"})), 400
        ensure_user_exists(email, plan="FREE")
        ok, err = check_verification_code(email, code)
        if ok:
            token = create_jwt(email)
            with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET email_verified=TRUE WHERE email=%s", (email,))
                    conn.commit()
            log_security_event("verify_code_success", email=email, ip=ip, endpoint="/verify_code")
            return _build_cors_response(jsonify({"success": True, "token": token}))
        else:
            log_security_event("verify_code_failed", email=email, ip=ip, endpoint="/verify_code", details=err)
            return _build_cors_response(jsonify({"success": False, "error": err})), 403
    except Exception as e:
        log.error(f"Verification failed: {e}")
        log_security_event("verification_code_error", email=None, ip=None, endpoint="/verify_code", details=str(e))
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/newsletter_subscribe", methods=["POST"])
@limiter.limit("3 per hour", key_func=lambda: get_logged_in_email() or get_remote_address())
@login_required
def newsletter_subscribe_route():
    print("NEWSLETTER_SUBSCRIBE ENDPOINT HIT")
    try:
        print("Parsing JSON for newsletter subscribe...")
        data = request.get_json(force=True)
        # user_email is sent from frontend, but we always use logged-in email for subscription
        email = get_logged_in_email()
        ip = get_remote_address()
        print(f"newsletter_subscribe email={email}")

        if not email:
            log_security_event("newsletter_failed", email=email, ip=ip, endpoint="/newsletter_subscribe",
                               details="Missing user_email")
            return _build_cors_response(jsonify({"success": False, "error": "Missing user_email"})), 400

        # Make sure user exists (keeps your user table tidy for analytics/attribution)
        ensure_user_exists(email, plan="FREE")

        # ✅ No plan gating here — open to all plans
        result = subscribe_to_newsletter(email)

        log_security_event("newsletter_subscribe_attempt", email=email, ip=ip,
                           endpoint="/newsletter_subscribe", details=f"result={result}")
        return _build_cors_response(jsonify({"success": result}))
    except Exception as e:
        log.error(f"Newsletter error: {e}")
        log_security_event("newsletter_error", email=None, ip=None,
                           endpoint="/newsletter_subscribe", details=str(e))
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/telegram_opt_in", methods=["POST"])
@limiter.limit("3 per hour", key_func=lambda: request.get_json(force=True).get("telegram_handle", get_remote_address()))
def telegram_opt_in_route():
    print("TELEGRAM_OPT_IN ENDPOINT HIT")
    try:
        print("Parsing JSON for telegram opt-in...")
        data = request.get_json(force=True)
        handle = (data.get("telegram_handle") or "").strip()
        ip = get_remote_address()
        print(f"telegram_opt_in handle={handle}")

        if not handle:
            log_security_event("telegram_opt_in_failed", email=None, ip=ip, endpoint="/telegram_opt_in", details="Missing telegram_handle")
            return _build_cors_response(jsonify({"success": False, "error": "Missing telegram_handle"})), 400

        # If the user is logged in, associate with their email
        try:
            email = get_logged_in_email()
        except Exception:
            email = None

        # Save to DB (add table if needed, see DB section below)
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS telegram_opt_ins (
                        id SERIAL PRIMARY KEY,
                        email TEXT,
                        telegram_handle TEXT NOT NULL,
                        opted_in_at TIMESTAMP NOT NULL DEFAULT NOW()
                    );
                """)
                cur.execute(
                    "INSERT INTO telegram_opt_ins (email, telegram_handle) VALUES (%s, %s)",
                    (email, handle)
                )
                conn.commit()

        log_security_event("telegram_opt_in", email=email, ip=ip, endpoint="/telegram_opt_in", details=f"handle={handle}")
        return _build_cors_response(jsonify({"success": True}))
    except Exception as e:
        log.error(f"Telegram opt-in error: {e}")
        log_security_event("telegram_opt_in_error", email=None, ip=None, endpoint="/telegram_opt_in", details=str(e))
        return _build_cors_response(jsonify({"success": False, "error": str(e)})), 500

@app.route("/presets", methods=["GET"])
def get_presets():
    try:
        category = request.args.get("category")
        limit = int(request.args.get("limit", 50))
        with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
            with conn.cursor() as cur:
                if category:
                    cur.execute(
                        "SELECT id, question, category FROM presets WHERE category = %s ORDER BY id LIMIT %s",
                        (category, limit)
                    )
                else:
                    cur.execute(
                        "SELECT id, question, category FROM presets ORDER BY id LIMIT %s",
                        (limit,)
                    )
                rows = cur.fetchall()
        return _build_cors_response(jsonify([
            {"id": row[0], "question": row[1], "category": row[2]}
            for row in rows
        ]))
    except Exception as e:
        log.error(f"🔥 Error fetching presets: {e}")
        return _build_cors_response(jsonify({"error": "Internal server error"})), 500

@app.route("/alerts", methods=["GET"])
@login_required
def get_alerts():
    """
    Returns clean, enriched alerts from the alerts table for frontend display.
    Supports optional filtering by region, category, risk_level, etc. via query params.
    Requires user to be logged in, to be PRO/Enterprise, and not to exceed plan quota.
    """
    try:
        region = request.args.get("region")
        category = request.args.get("category")
        risk_level = request.args.get("risk_level")
        limit = int(request.args.get("limit", 100))

        user_email = get_logged_in_email()
        plan_limits = get_plan_limits(user_email)
        plan_name = plan_limits.get("name", "FREE")

        # 1. Plan gating: restrict to PRO/Enterprise
        if plan_name not in ["PRO", "Enterprise"]:
            log_security_event(
                "plan_denied",
                email=user_email,
                ip=get_remote_address(),
                endpoint="/alerts",
                plan=plan_name,
                details="Alerts access not available for this plan"
            )
            return _build_cors_response(jsonify({
                "error": "Alerts are only available to PRO or Enterprise users. Please upgrade your plan."
            })), 403

        # 2. Quota check: travel_alerts_per_month
        # Using summaries_used for alert quota, for fast implementation.
        usage = get_usage(user_email)
        alerts_used = usage.get("summaries_used", 0)
        alerts_limit = plan_limits.get("travel_alerts_per_month")
        if alerts_limit is not None and alerts_limit > 0 and alerts_used >= alerts_limit:
            log_security_event(
                "alerts_quota_exceeded",
                email=user_email,
                ip=get_remote_address(),
                endpoint="/alerts",
                plan=plan_name,
                details=f"Monthly alert quota reached. Used: {alerts_used}, Limit: {alerts_limit}"
            )
            return _build_cors_response(jsonify({
                "error": "You have reached your monthly security alerts quota. Upgrade or wait for reset.",
                "quota": {
                    "used": alerts_used,
                    "limit": alerts_limit
                }
            })), 429

        # Import the function that fetches clean alerts (from threat_engine)
        from threat_engine import get_clean_alerts

        alerts = get_clean_alerts(
            region=region,
            threat_label=category,
            threat_level=risk_level,
            limit=limit,
            user_email=user_email
        )

        # INCREMENT ALERT USAGE QUOTA
        # This makes quota enforcement work.
        from plan_utils import increment_user_summary_usage
        increment_user_summary_usage(user_email)

        # Ensure alerts are serializable (if using datetime objects)
        def clean_alert_dict(alert):
            return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in alert.items()}

        return _build_cors_response(jsonify({
            "alerts": [clean_alert_dict(a) for a in alerts],
            "quota": {
                "used": alerts_used + 1,  # Show incremented usage
                "limit": alerts_limit
            },
        }))
    except Exception as e:
        log.error(f"🔥 Error fetching alerts: {e}")
        return _build_cors_response(jsonify({"error": "Internal server error"})), 500

@app.errorhandler(404)
def not_found_error(error):
    print("404 Not Found Error")
    log.warning(f"404 Not Found: {error}")
    log_security_event("not_found", email=get_logged_in_email(), ip=get_remote_address(), endpoint=request.path)
    return _build_cors_response(jsonify({"error": "Not found"})), 404

@app.errorhandler(405)
def method_not_allowed_error(error):
    print("405 Method Not Allowed Error")
    log.warning(f"405 Method Not Allowed: {error}")
    log_security_event("method_not_allowed", email=get_logged_in_email(), ip=get_remote_address(), endpoint=request.path)
    return _build_cors_response(jsonify({"error": "Method not allowed"})), 405

@app.errorhandler(500)
def internal_error(error):
    print("500 Internal Server Error")
    log.error(f"500 Internal Server Error: {error}")
    log_security_event("internal_error", email=get_logged_in_email(), ip=get_remote_address(), endpoint=request.path, details=str(error))
    return _build_cors_response(jsonify({"error": "Internal server error"})), 500

def send_proactive_alerts():
    """Background thread: send daily proactive alerts to enterprise users."""
    while True:
        try:
            with psycopg2.connect(os.getenv("DATABASE_URL")) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT u.email FROM users u
                        JOIN plans p ON u.plan = p.name
                        WHERE p.proactive_feed_enabled = TRUE
                    """)
                    emails = [row[0] for row in cur.fetchall()]
                    for email in emails:
                        cur.execute("""
                            SELECT region, headline, risk_type, expected_window, recommended_action, trend, sources
                            FROM risk_watchlist WHERE active = TRUE
                        """)
                        risks = [
                            {
                                "region": r[0], "headline": r[1], "risk_type": r[2], "expected_window": r[3],
                                "recommended_action": r[4], "trend": r[5], "sources": r[6]
                            }
                            for r in cur.fetchall()
                        ]
                        log.info(f"Proactive alerts for {email}: {risks}")
            log.info("Proactive alert push completed.")
        except Exception as e:
            log.error(f"Proactive alert push error: {e}")
        time.sleep(86400)

if os.getenv("ENV") == "production":
    threading.Thread(target=send_proactive_alerts, daemon=True).start()

if __name__ == "__main__":
    log.info("🚀 Sentinel AI backend starting...")
    print("ENV is:", os.getenv("ENV"))
    print("PORT is:", PORT)
    if os.getenv("ENV") != "production":
        print("Starting Flask app on port", PORT)
        app.run(host="0.0.0.0", port=PORT)