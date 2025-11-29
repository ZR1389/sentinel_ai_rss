# security_log_utils.py — security/audit event logger (jsonb-native)

from __future__ import annotations
import logging
from datetime import datetime, timezone
import os
from typing import Any, Optional

import psycopg2
from psycopg2.extras import Json

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
AUTO_CREATE_TABLE = os.getenv("SECURITY_EVENTS_AUTOCREATE", "0").lower() in ("1", "true", "yes")

_table_checked = False

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

def _ensure_table_once():
    """Create table/index if missing (only if AUTO_CREATE_TABLE=1). Uses jsonb for `details`."""
    global _table_checked
    if _table_checked or not AUTO_CREATE_TABLE:
        return
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                  id         bigserial PRIMARY KEY,
                  event_type text        NOT NULL,
                  email      text,
                  ip         text,
                  endpoint   text,
                  plan       text,
                  details    jsonb,
                  created_at timestamptz NOT NULL DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sec_events_created_at
                  ON security_events(created_at);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sec_events_type_time
                  ON security_events(event_type, created_at);
            """)
            conn.commit()
    except Exception as e:
        log.warning("[SECURITY LOG INIT] Table ensure skipped: %s", e)
    finally:
        _table_checked = True

def _json_safe(val: Any):
    """
    Wrap value for jsonb column. If it can't be JSON-encoded, fall back to string.
    """
    try:
        return Json(val)  # psycopg2 will serialize
    except Exception:
        try:
            return Json({"_str": str(val)})
        except Exception:
            return Json(None)

def log_security_event(
    event_type: str,
    *,
    email: Optional[str] = None,
    ip: Optional[str] = None,
    endpoint: Optional[str] = None,
    plan: Optional[str] = None,
    details: Any = None
) -> None:
    """
    Dual logger: writes to app logs + inserts a row into `security_events` with jsonb `details`.
    Never raises; on DB errors, only logs to app logs.
    """
    # App/console log (UTC)
    now_iso = datetime.now(timezone.utc).isoformat()
    log.info(
        "[SECURITY] [%s] Event=%s | Email=%s | IP=%s | Endpoint=%s | Plan=%s | Details=%s",
        now_iso, event_type, email, ip, endpoint, plan, details
    )

    if not DATABASE_URL:
        return

    _ensure_table_once()

    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO security_events (event_type, email, ip, endpoint, plan, details)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (event_type, email, ip, endpoint, plan, _json_safe(details))
            )
            conn.commit()
    except Exception as e:
        # Never break caller flow on logging failure
        log.error("[SECURITY LOG DB ERROR] Could not insert event: %s", e)
