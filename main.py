# main.py — Sentinel AI App API (JWT-guarded) • v2025-08-13
# Notes:
# - Only /chat counts toward plan usage, and only AFTER a successful advisory.
# - /rss/run and /engine/run are backend ops and are NOT metered.
# - Newsletter is UNMETERED; requires verified login.
# - PDF/Email/Push/Telegram are UNMETERED but require a PAID plan.
# - Auth/verification endpoints added and left unmetered.
# - Chat now REQUIRES verified email (403 if not verified).

from __future__ import annotations
import os
import logging
import traceback
from typing import Any, Dict, Optional

from flask import Flask, request, jsonify, make_response

# ---------- Logging ----------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("sentinel.main")

# ---------- App ----------
app = Flask(__name__)

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
        require_paid_feature,  # for gated features
        get_plan,              # plan lookup for /auth/refresh access token issuance
    )
except Exception as e:
    logger.error("plan_utils import failed: %s", e)
    ensure_user_exists = get_plan_limits = check_user_message_quota = increment_user_message_usage = None
    require_paid_feature = None
    get_plan = None

# Advisor — allow a couple of function names for resilience
_advisor_callable = None
try:
    from advisor import handle_user_query as _advisor_callable
except Exception:
    try:
        from advisor import generate_advisory as _advisor_callable
    except Exception as e:
        logger.error("advisor import failed: %s", e)
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

# DB utils for some handy reads
try:
    from db_utils import fetch_all, fetch_one
except Exception:
    fetch_all = None
    fetch_one = None

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

    return _build_cors_response(jsonify({
        "ok": True,
        "access_token": access_token,
        "refresh_bundle": refresh_bundle,  # "refresh_id:token"
        "email_verified": bool(verified),
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

@app.route("/auth/status", methods=["GET"])
def auth_status():
    email = request.headers.get("X-User-Email") or request.args.get("email") or ""
    email = email.strip().lower()
    if not email:
        return _build_cors_response(make_response(jsonify({"error": "Missing email"}), 400))
    verified = _is_verified(email)
    plan_name = "FREE"
    if get_plan:
        try:
            p = get_plan(email)
            if isinstance(p, str) and p:
                plan_name = p.upper()
        except Exception:
            pass
    return _build_cors_response(jsonify({"ok": True, "email_verified": bool(verified), "plan": plan_name}))

# ---------- Chat (metered AFTER success) ----------
@app.route("/chat", methods=["POST", "OPTIONS"])
def chat_options():
    # keep preflight separate to preserve decorator behavior below
    if request.method == "OPTIONS":
        return _build_cors_response(make_response("", 204))
    return _chat_impl()

@app.route("/chat", methods=["POST"])
@login_required
def _chat_impl():
    payload = _json_request()
    query = (payload.get("query") or "").strip()
    profile_data = payload.get("profile_data") or {}
    input_data = payload.get("input_data") or {}
    email = get_logged_in_email()  # from JWT

    if not query:
        return _build_cors_response(make_response(jsonify({"error": "Missing 'query'"}), 400))
    if _advisor_callable is None:
        return _build_cors_response(make_response(jsonify({"error": "Advisor unavailable"}), 503))

    # ✅ Require verified email for chat
    try:
        verified = False
        if verification_status:
            try:
                verified, _ = verification_status(email)
            except Exception:
                verified = _is_verified(email)
        else:
            verified = _is_verified(email)
        if not verified:
            return _build_cors_response(
                make_response(jsonify({"error": "Email not verified", "verification_required": True}), 403)
            )
    except Exception as e:
        logger.error("verification check failed: %s", e)
        return _build_cors_response(make_response(jsonify({"error": "Verification check failed"}), 500))

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
        return _build_cors_response(make_response(jsonify({"error": "Telegram dispatcher unavailable"}), 503))

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

# ---------- Alerts debug ----------
@app.route("/alerts/latest", methods=["GET"])
def alerts_latest():
    if fetch_all is None:
        return _build_cors_response(make_response(jsonify({"error": "DB helper unavailable"}), 503))

    limit = int(request.args.get("limit", 20))
    region = request.args.get("region")
    country = request.args.get("country")
    city = request.args.get("city")

    where = []
    params = []
    if region:
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
        SELECT uuid, published, source, title, city, country, category, subcategory,
               threat_level, score, trend_direction, anomaly_flag, domains
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

# ---------- Entrypoint ----------
if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    debug = bool(os.getenv("FLASK_DEBUG", "").lower() in ("1","true","yes","y"))
    logger.info("Starting Sentinel AI API on %s:%s (debug=%s)", host, port, debug)
    app.run(host=host, port=port, debug=debug)
