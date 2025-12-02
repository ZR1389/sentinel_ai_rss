# webpush_endpoints.py
from __future__ import annotations
import os
import json
import logging
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, request, jsonify, g
import jwt

logger = logging.getLogger("webpush_endpoints")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# Feature gate (same idea as in your dispatchers)
PUSH_ENABLED = os.getenv("PUSH_ENABLED", "false").lower() in ("1", "true", "yes", "y")
DATABASE_URL = os.getenv("DATABASE_URL")

# Paid plan check (reuse your plan gating approach)
try:
    from utils.plan_utils import user_has_paid_plan as is_paid_user
except Exception:
    def is_paid_user(_email: str) -> bool:
        return False

webpush_bp = Blueprint("webpush", __name__)

# ---------- DB helpers ----------
def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

# ---------- Auth helpers ----------
def _extract_email_from_jwt(token: str) -> Optional[str]:
    """
    Best-effort decode: HS256 with JWT_SECRET if present; otherwise try RS256 if JWT_PUBLIC_KEY present.
    Adjust to match your real JWT signing.
    """
    jwt_alg = os.getenv("JWT_ALG", "HS256")
    try:
        if jwt_alg.upper().startswith("HS"):
            secret = os.getenv("JWT_SECRET")
            if not secret:
                return None
            payload = jwt.decode(token, secret, algorithms=[jwt_alg])
        else:
            pub = os.getenv("JWT_PUBLIC_KEY")
            if not pub:
                return None
            payload = jwt.decode(token, pub, algorithms=[jwt_alg])

        email = (payload.get("email") or payload.get("sub") or "").strip().lower()
        return email or None
    except Exception:
        return None

def _unauthorized(msg="Unauthorized"):
    from flask import Response
    return Response(json.dumps({"error": msg}), status=401, mimetype="application/json")

def _forbidden(msg="Forbidden"):
    from flask import Response
    return Response(json.dumps({"error": msg}), status=403, mimetype="application/json")

# --- replace the auth helper section in webpush_endpoints.py with this ---
def _current_user_email() -> str:
    # 1) If your app already put the email on the request context, use it
    if getattr(request, "user_email", None):
        return str(request.user_email).strip().lower()
    if getattr(g, "user_email", None):
        return str(g.user_email).strip().lower()

    # 2) Dev/testing fallback: header (your front-end can send it if needed)
    hdr = request.headers.get("X-User-Email", "").strip().lower()
    if hdr:
        return hdr

    # 3) Best-effort JWT decode only if keys exist (won’t break if you don’t set them)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
        email = _extract_email_from_jwt(token)  # uses helper above
        if email:
            return email

    # 4) No way to know email -> unauthorized
    raise _unauthorized("Unauthorized")

# ---------- Routes ----------
@webpush_bp.route("/push_status", methods=["GET"])
def push_status():
    try:
        email = _current_user_email()
    except Exception:
        return _unauthorized()

    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM web_push_subscriptions WHERE user_email=%s LIMIT 1",
            (email,),
        )
        enabled = cur.fetchone() is not None
    return jsonify({"enabled": enabled})

@webpush_bp.route("/subscribe_push", methods=["POST"])
def subscribe_push():
    if not PUSH_ENABLED:
        return _forbidden("Push disabled")
    try:
        email = _current_user_email()
    except Exception:
        return _unauthorized()

    if not is_paid_user(email):
        return _forbidden("Paid plan required for push notifications.")

    data = request.get_json(silent=True) or {}
    sub = (data.get("subscription") or {})
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth_key = keys.get("auth")

    if not (endpoint and p256dh and auth_key):
        return _unauthorized("Invalid subscription payload")

    ua = request.headers.get("User-Agent")

    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO web_push_subscriptions (user_email, endpoint, p256dh, auth, user_agent)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (endpoint) DO UPDATE SET
              user_email = EXCLUDED.user_email,
              p256dh     = EXCLUDED.p256dh,
              auth       = EXCLUDED.auth,
              user_agent = EXCLUDED.user_agent
            """,
            (email, endpoint, p256dh, auth_key, ua),
        )
        conn.commit()

    return jsonify({"ok": True})

@webpush_bp.route("/unsubscribe_push", methods=["POST"])
def unsubscribe_push():
    try:
        email = _current_user_email()
    except Exception:
        return _unauthorized()

    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")

    with _conn() as conn, conn.cursor() as cur:
        if endpoint:
            cur.execute(
                "DELETE FROM web_push_subscriptions WHERE user_email=%s AND endpoint=%s",
                (email, endpoint),
            )
        else:
            cur.execute(
                "DELETE FROM web_push_subscriptions WHERE user_email=%s",
                (email,),
            )
        conn.commit()

    return jsonify({"ok": True})

# Optional: send a test push to all of the user's saved browser subscriptions
@webpush_bp.route("/push/test", methods=["POST"])
def push_test():
    try:
        email = _current_user_email()
    except Exception:
        return _unauthorized()

    # Load subs
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT endpoint, p256dh, auth FROM web_push_subscriptions WHERE user_email=%s",
            (email,),
        )
        rows = cur.fetchall()

    if not rows:
        return jsonify({"error": "No browser subscriptions on file."}), 404

    from webpush_send import send_web_push

    payload = {
        "title": "Sentinel AI",
        "body": "Test web push delivered ✅",
        "url": "/dashboard",
    }

    dead = []
    sent = 0
    for r in rows:
        sub = {"endpoint": r["endpoint"], "keys": {"p256dh": r["p256dh"], "auth": r["auth"]}}
        res = send_web_push(sub, payload)
        if res is True:
            sent += 1
        elif res is False:
            dead.append(r["endpoint"])

    # Clean up expired endpoints
    if dead:
        with _conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "DELETE FROM web_push_subscriptions WHERE endpoint=%s",
                [(e,) for e in dead],
            )
            conn.commit()

    return jsonify({"ok": True, "sent": sent, "removed": len(dead)})
