import logging
from datetime import datetime
import os
import psycopg2

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

def log_security_event(event_type, email=None, ip=None, endpoint=None, plan=None, details=None):
    # Log to application logs
    log.info(
        f"[SECURITY] [{datetime.utcnow().isoformat()}] Event={event_type} | "
        f"Email={email} | IP={ip} | Endpoint={endpoint} | Plan={plan} | Details={details}"
    )

    # Also log to database
    try:
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO security_events (event_type, email, ip, endpoint, plan, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (event_type, email, ip, endpoint, plan, str(details) if details is not None else None))
            conn.commit()
            cur.close()
            conn.close()
    except Exception as e:
        log.error(f"[SECURITY LOG DB ERROR] Could not insert event: {e}")