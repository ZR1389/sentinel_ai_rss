# auth_utils.py — auth & profile helpers • v2025-08-13

from __future__ import annotations
import os
import jwt
import secrets
import datetime as dt
from functools import wraps
from typing import Optional, Tuple, Dict, Any

from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

from security_log_utils import log_security_event

DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET")  # DO NOT default in production
JWT_ALGORITHM = os.getenv("JWT_ALG", "HS256")
JWT_EXP_MINUTES = int(os.getenv("JWT_EXP_MINUTES", "60"))          # access token lifetime
REFRESH_EXP_DAYS = int(os.getenv("REFRESH_EXP_DAYS", "30"))        # refresh lifetime

DEFAULT_PLAN = os.getenv("DEFAULT_PLAN", "FREE").upper()

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

# ---------------- Passwords ----------------

def hash_password(plain: str) -> str:
    return generate_password_hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return check_password_hash(hashed, plain)
    except Exception:
        return False

# ---------------- Users / Profiles ----------------

def create_user(email: str, password: Optional[str] = None, name: Optional[str] = None, employer: Optional[str] = None, plan: Optional[str] = None) -> bool:
    """
    Creates a user if not exists. Returns True if created or already exists.
    """
    plan = (plan or DEFAULT_PLAN).upper()
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT email FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            return True
        pwd_hash = hash_password(password) if password else None
        cur.execute("""
            INSERT INTO users (email, plan, name, employer, password_hash, email_verified)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (email, plan, name, employer, pwd_hash, False))
        conn.commit()
        log_security_event(event_type="user_created_auth", email=email, details=f"plan={plan}")
        return True

def ensure_user_profile(email: str) -> None:
    """
    Creates a minimal profile if user_profiles exists. Safe if table missing.
    """
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='user_profiles'")
            if not cur.fetchone():
                return
            cur.execute("SELECT 1 FROM user_profiles WHERE email=%s", (email,))
            if cur.fetchone():
                return
            cur.execute("INSERT INTO user_profiles (email) VALUES (%s)", (email,))
            conn.commit()
            log_security_event(event_type="profile_created", email=email, details="auto-init")
    except Exception as e:
        # Do not block auth on profile errors
        log_security_event(event_type="profile_create_error", email=email, details=str(e))

# ---------------- JWTs ----------------

def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def create_access_token(user_email: str, plan: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET not set")
    payload = {
        "user_email": user_email,
        "plan": (plan or DEFAULT_PLAN).upper(),
        "iat": int(_now_utc().timestamp()),
        "exp": int((_now_utc() + dt.timedelta(minutes=JWT_EXP_MINUTES)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def create_refresh_token(user_email: str) -> Tuple[str, str]:
    """
    Returns (refresh_token, refresh_id). Store hashed token server-side for rotation.
    """
    token = secrets.token_urlsafe(48)
    refresh_id = secrets.token_hex(16)
    exp = _now_utc() + dt.timedelta(days=REFRESH_EXP_DAYS)
    token_hash = generate_password_hash(token)  # reuse strong hash
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO refresh_tokens (refresh_id, email, token_hash, expires_at, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (refresh_id) DO NOTHING
        """, (refresh_id, user_email, token_hash, exp.replace(tzinfo=None)))
        conn.commit()
    return token, refresh_id

def rotate_refresh_token(refresh_id: str, token: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Verifies and rotates a refresh token. Returns (ok, new_token, new_refresh_id).
    """
    try:
        with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT email, token_hash, expires_at FROM refresh_tokens WHERE refresh_id=%s", (refresh_id,))
            row = cur.fetchone()
            if not row:
                return False, None, None
            if row["expires_at"] and row["expires_at"] < _now_utc().replace(tzinfo=None):
                # expired
                cur.execute("DELETE FROM refresh_tokens WHERE refresh_id=%s", (refresh_id,))
                conn.commit()
                return False, None, None
            if not check_password_hash(row["token_hash"], token):
                return False, None, None
            # rotate
            new_token, new_id = create_refresh_token(row["email"])
            cur.execute("DELETE FROM refresh_tokens WHERE refresh_id=%s", (refresh_id,))
            conn.commit()
            return True, new_token, new_id
    except Exception as e:
        log_security_event(event_type="refresh_rotate_error", details=str(e))
        return False, None, None

def decode_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth.split(" ", 1)[1].strip()
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            log_security_event(event_type="auth_token_invalid", details="Invalid or expired JWT")
            return jsonify({"error": "Invalid or expired token"}), 401
        g.user_email = payload.get("user_email")
        g.user_plan = payload.get("plan")
        return f(*args, **kwargs)
    return decorated

def get_logged_in_email() -> Optional[str]:
    return getattr(g, "user_email", None)

# ---------------- Signup / Login helpers ----------------

def register_user(email: str, password: Optional[str], name: Optional[str] = None, employer: Optional[str] = None, plan: Optional[str] = None) -> Tuple[bool, str]:
    """
    Creates user, sets password, initializes profile. Returns (ok, msg).
    """
    try:
        created = create_user(email, password, name, employer, plan)
        ensure_user_profile(email)
        return True, "User registered"
    except Exception as e:
        log_security_event(event_type="register_error", email=email, details=str(e))
        return False, "Registration failed"

def authenticate_user(email: str, password: str) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """
    Verifies password; on success returns (ok, msg, access_token, refresh_token_bundle)
    where refresh_token_bundle is 'refresh_id:token' for transport simplicity.
    Enforces users.is_active == TRUE.
    """
    try:
        with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT email, password_hash, plan, email_verified, is_active "
                "FROM users WHERE email=%s",
                (email,)
            )
            row = cur.fetchone()
            if not row or not row.get("password_hash"):
                return False, "Invalid credentials", None, None

            # Block disabled accounts
            if not row.get("is_active", True):
                return False, "Account disabled", None, None

            if not verify_password(password, row["password_hash"]):
                return False, "Invalid credentials", None, None

            access = create_access_token(email, row.get("plan") or DEFAULT_PLAN)
            rt, rid = create_refresh_token(email)
            bundle = f"{rid}:{rt}"
            return True, "OK", access, bundle
    except Exception as e:
        log_security_event(event_type="auth_error", email=email, details=str(e))
        return False, "Auth failed", None, None
