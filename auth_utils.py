import os
import jwt
import datetime
from functools import wraps
from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2

from security_log_utils import log_security_event

JWT_SECRET = os.getenv("JWT_SECRET", "supersecret")
JWT_ALGORITHM = "HS256"
JWT_EXP_MINUTES = int(os.getenv("JWT_EXP_MINUTES", "60"))

def get_db():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    return conn

def create_jwt(email):
    exp = datetime.datetime.utcnow() + datetime.timedelta(minutes=JWT_EXP_MINUTES)
    payload = {"user_email": email, "exp": exp}
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    log_security_event(
        event_type="jwt_created",
        email=email,
        details=f"JWT created with expiry {exp.isoformat()}"
    )
    return token

def decode_jwt(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        log_security_event(
            event_type="jwt_decoded",
            email=payload.get("user_email"),
            details="JWT decoded successfully"
        )
        return payload
    except jwt.ExpiredSignatureError:
        log_security_event(
            event_type="jwt_expired",
            details="JWT expired when decoding"
        )
        return None
    except jwt.InvalidTokenError:
        log_security_event(
            event_type="jwt_invalid",
            details="JWT invalid when decoding"
        )
        return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # PATCH: Allow OPTIONS requests for CORS preflight
        if request.method == "OPTIONS":
            return f(*args, **kwargs)
        auth_header = request.headers.get("Authorization", None)
        if not auth_header or not auth_header.startswith("Bearer "):
            log_security_event(
                event_type="auth_missing",
                details="Missing or invalid Authorization header"
            )
            return jsonify({"error": "Authentication required"}), 401
        token = auth_header.split(" ", 1)[1]
        payload = decode_jwt(token)
        if not payload or "user_email" not in payload:
            log_security_event(
                event_type="auth_failed",
                details="Invalid or expired JWT"
            )
            return jsonify({"error": "Invalid or expired token"}), 401
        g.user_email = payload["user_email"]  # Store for downstream use
        log_security_event(
            event_type="auth_success",
            email=payload["user_email"],
            details="User authenticated"
        )
        return f(*args, **kwargs)
    return decorated

def get_logged_in_email():
    # Use Flask's global context (set in login_required)
    return getattr(g, "user_email", None)