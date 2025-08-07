import os
import logging
from pathlib import Path
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from datetime import date, datetime
from threat_scorer import assess_threat_level
from threat_engine import get_clean_alerts
from plan_utils import get_plan_limits, require_plan_feature

import psycopg2
from psycopg2.extras import RealDictCursor

# --- Logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
DATABASE_URL = os.getenv("DATABASE_URL")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

def get_threat_color(level):
    if level == "Low":
        return (0, 150, 0)
    elif level == "Moderate":
        return (255, 165, 0)
    elif level == "High":
        return (255, 0, 0)
    elif level == "Critical":
        return (139, 0, 0)
    else:
        return (100, 100, 100)

def get_user_pdf_usage(email):
    """
    Returns (used, last_reset) for the given user.
    """
    if not DATABASE_URL:
        log.error("DATABASE_URL not set for DB usage tracking.")
        return 0, None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT pdf_reports_used, pdf_reports_last_reset
            FROM user_usage
            WHERE email = %s
        """, (email,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return 0, None
        return row.get("pdf_reports_used", 0) or 0, row.get("pdf_reports_last_reset")
    except Exception as e:
        log.error(f"Error fetching PDF usage for {email}: {e}")
        return 0, None

def set_user_pdf_usage(email, used, last_reset):
    if not DATABASE_URL:
        log.error("DATABASE_URL not set for DB usage tracking.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            UPDATE user_usage
            SET pdf_reports_used = %s, pdf_reports_last_reset = %s
            WHERE email = %s
        """, (used, last_reset, email))
        conn.commit()
        cur.close()
        conn.close()
        log.info(f"Set pdf_reports_used={used}, pdf_reports_last_reset={last_reset} for {email}")
    except Exception as e:
        log.error(f"Error updating PDF usage for {email}: {e}")

def increment_user_pdf_usage(email):
    # Handles monthly reset and increments usage
    used, last_reset = get_user_pdf_usage(email)
    today = date.today()
    now_month = today.strftime("%Y-%m")
    last_month = None
    if last_reset:
        try:
            last_month = last_reset.strftime("%Y-%m") if isinstance(last_reset, date) else str(last_reset)[:7]
        except Exception:
            last_month = str(last_reset)[:7]
    if last_month != now_month:
        # Reset for new month
        set_user_pdf_usage(email, 1, today)
        return 1
    else:
        set_user_pdf_usage(email, used + 1, today)
        return used + 1

def generate_pdf(output_path=None, email=None):
    # --- ENFORCE PLAN GATING AND QUOTA FOR PDF GENERATION ---
    if email:
        plan_limits = get_plan_limits(email)
        quota = plan_limits.get("pdf_reports_per_month", 0)
        if not plan_limits.get("pdf_reports_per_month", 0):
            log.info(f"User {email} not allowed to generate PDF (quota 0).")
            raise PermissionError(f"User {email} not allowed to generate PDF: quota 0.")
        if not require_plan_feature(email, "custom_pdf_briefings_frequency"):
            log.info(f"User {email} not allowed to generate PDF (missing custom_pdf_briefings_frequency feature).")
            raise PermissionError(f"User {email} not allowed to generate PDF: missing feature.")
        used, last_reset = get_user_pdf_usage(email)
        today = date.today()
        now_month = today.strftime("%Y-%m")
        last_month = None
        if last_reset:
            try:
                last_month = last_reset.strftime("%Y-%m") if isinstance(last_reset, date) else str(last_reset)[:7]
            except Exception:
                last_month = str(last_reset)[:7]
        if last_month != now_month:
            used = 0  # Reset for new month

        if quota is not None and quota > 0 and used >= quota:
            log.info(f"User {email} has reached their monthly PDF quota ({used}/{quota}).")
            raise PermissionError(f"User {email} has reached their monthly PDF quota ({used}/{quota}).")

    raw_alerts = get_clean_alerts(user_email=email) if email else get_clean_alerts()
    scored_alerts = []

    for alert in raw_alerts:
        try:
            level_result = assess_threat_level(f"{alert['title']}: {alert['summary']}")
            if isinstance(level_result, dict):
                level = level_result.get("threat_label", "Unrated")
            else:
                level = str(level_result)
        except Exception as e:
            log.error(f"[generate_pdf][assess_threat_level Error] {e}")
            level = "Unrated"

        scored_alerts.append({
            "title": alert["title"],
            "summary": alert["summary"],
            "link": alert.get("link"),
            "source": alert["source"],
            "level": level
        })

    class PDF(FPDF):
        def header(self):
            self.set_font("NotoSans", "", 16)
            self.set_text_color(0)
            self.cell(0, 10, f"Sentinel AI Daily Brief — {date.today().isoformat()}", ln=True, align='C')
            self.ln(8)

        def footer(self):
            self.set_y(-15)
            self.set_font("NotoSans", "", 8)
            self.set_text_color(100)
            self.cell(0, 10, "Sentinel AI Powered by Zika Risk | www.zikarisk.com", align='C')

        def chapter_body(self, alerts):
            for alert in alerts:
                self.set_text_color(0)
                self.set_font("NotoSans", "", 13)
                self.multi_cell(0, 8, alert["title"], align='L')
                self.ln(1)

                self.set_text_color(100, 100, 100)
                self.set_font("NotoSans", "", 10)
                self.cell(0, 6, f"Source: {alert['source']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                self.set_text_color(*get_threat_color(alert["level"]))
                self.set_font("NotoSans", "", 10)
                self.cell(0, 6, f"Threat Level: {alert['level']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                self.set_text_color(0)
                self.set_font("NotoSans", "", 11)
                self.multi_cell(0, 7, alert["summary"], align='L')

                self.ln(6)

    pdf = PDF()
    font_path = Path(__file__).parent / "fonts" / "NotoSans-Regular.ttf"
    if not font_path.exists():
        log.error(f"Font file not found: {font_path}")
        raise FileNotFoundError(f"Font file not found: {font_path}")
    pdf.add_font("NotoSans", "", str(font_path), uni=True)
    pdf.set_font("NotoSans", "", 12)
    pdf.add_page()
    pdf.chapter_body(scored_alerts)

    if output_path is None:
        # Use a safe temp dir in cloud, fallback to Desktop for local
        try:
            tmp_dir = Path("/tmp")
            tmp_dir.mkdir(exist_ok=True)
            output_path = str(tmp_dir / f"daily-brief-{date.today().isoformat()}.pdf")
        except Exception:
            output_path = str(Path.home() / f"Desktop/daily-brief-{date.today().isoformat()}.pdf")
    pdf.output(output_path)
    log.info(f"PDF created: {output_path}")

    # Only increment usage if email is present (i.e. user context)
    if email:
        increment_user_pdf_usage(email)
    return output_path

if __name__ == "__main__":
    # Example usage: generate_pdf(email="user@example.com")
    generate_pdf()