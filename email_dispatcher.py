from fpdf import FPDF
from datetime import date
from threat_scorer import assess_threat_level
from threat_engine import get_clean_alerts
import os
from dotenv import load_dotenv
import smtplib
import ssl
import tempfile
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
import re
import logging

from plan_utils import get_plan_limits, require_plan_feature, check_user_pdf_quota, increment_user_pdf_usage
from security_log_utils import log_security_event

# --- Configurable constants ---
FONT_PATH = "fonts/NotoSans-Regular.ttf"
FONT_FAMILY = "Noto"
PDF_ALERT_LIMIT = 5  # Max alerts per PDF/report

# --- Logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

if not all([SENDER_EMAIL, SENDER_PASSWORD, SMTP_SERVER]):
    log.warning("Some email environment variables are missing! Check Railway service variables.")

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

def sanitize_filename(email):
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", email)

def generate_pdf(email, alerts, plan_name, region=None):
    class PDF(FPDF):
        def header(self):
            heading = f"Sentinel AI Daily Brief — {plan_name.upper()} — {date.today().isoformat()}"
            self.set_font(FONT_FAMILY, "B", 16)
            self.set_text_color(237, 0, 0)
            self.cell(0, 10, heading, ln=True, align='C')
            self.ln(2)
            self.set_font(FONT_FAMILY, "I", 11)
            self.set_text_color(100)
            region_str = f" | Region: {region}" if region else ""
            alerts_count = len(alerts)
            self.cell(
                0,
                10,
                f"Showing top {PDF_ALERT_LIMIT} alerts (total: {alerts_count}){region_str}",
                ln=True,
                align='C'
            )
            self.ln(5)

        def chapter_body(self, alerts):
            for alert in alerts:
                self.set_text_color(0)
                self.set_font(FONT_FAMILY, "B", 12)
                self.multi_cell(0, 10, f"{alert['title']}", align='L')

                level_color = get_threat_color(alert["level"])
                self.set_text_color(100, 100, 100)
                self.set_font(FONT_FAMILY, "I", 11)
                self.cell(0, 8, f"Source: {alert['source']}", ln=True)

                self.set_text_color(*level_color)
                self.cell(0, 8, f"Threat Level: {alert['level']}", ln=True)

                self.set_text_color(0)
                self.set_font(FONT_FAMILY, "", 12)
                self.multi_cell(0, 10, f"{alert['summary']}", align='L')

                self.set_font(FONT_FAMILY, "I", 11)
                if alert.get("forecast"):
                    self.set_text_color(0, 60, 120)
                    self.multi_cell(0, 8, f"Forecast: {alert['forecast']}", align='L')
                if alert.get("historical_context"):
                    self.set_text_color(0, 60, 120)
                    self.multi_cell(0, 8, f"Historical Context: {alert['historical_context']}", align='L')
                if alert.get("sentiment"):
                    self.set_text_color(120, 80, 0)
                    self.multi_cell(0, 8, f"Sentiment: {alert['sentiment']}", align='L')
                if alert.get("legal_risk"):
                    self.set_text_color(120, 0, 80)
                    self.multi_cell(0, 8, f"Legal/Regulatory: {alert['legal_risk']}", align='L')
                if alert.get("inclusion_info"):
                    self.set_text_color(0, 80, 40)
                    self.multi_cell(0, 8, f"Accessibility/Inclusion: {alert['inclusion_info']}", align='L')
                if alert.get("profession_info"):
                    self.set_text_color(40, 40, 140)
                    self.multi_cell(0, 8, f"Profession: {alert['profession_info']}", align='L')

                if alert["link"]:
                    self.set_text_color(0, 0, 255)
                    self.set_font(FONT_FAMILY, "", 11)
                    self.cell(0, 10, alert["link"], ln=True, link=alert["link"])

                self.set_font(FONT_FAMILY, "", 12)
                self.set_text_color(0)
                self.ln(6)

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

    scored_alerts = []
    for alert in alerts[:PDF_ALERT_LIMIT]:
        level_result = assess_threat_level(f"{alert['title']}: {alert['summary']}")
        if isinstance(level_result, dict):
            level = level_result.get("threat_label", "Unknown")
        else:
            level = str(level_result)
        scored_alerts.append({
            "title": alert["title"],
            "summary": alert["summary"],
            "source": alert["source"],
            "link": alert["link"],
            "level": level,
            "forecast": alert.get("forecast", ""),
            "historical_context": alert.get("historical_context", ""),
            "sentiment": alert.get("sentiment", ""),
            "legal_risk": alert.get("legal_risk", ""),
            "inclusion_info": alert.get("inclusion_info", ""),
            "profession_info": alert.get("profession_info", ""),
        })

    pdf = PDF()
    pdf.add_font(FONT_FAMILY, "", FONT_PATH, uni=True)
    pdf.add_font(FONT_FAMILY, "B", FONT_PATH, uni=True)
    pdf.add_font(FONT_FAMILY, "I", FONT_PATH, uni=True)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.chapter_body(scored_alerts)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        pdf.output(temp_pdf.name)
        filename = temp_pdf.name
    log.info(f"PDF report generated: {filename} for {email}")
    log_security_event(
        event_type="pdf_generated",
        email=email,
        details=f"PDF file {filename} generated for {email}, plan {plan_name}, region {region}"
    )
    return filename

def send_pdf_report(email, region=None):
    plan_info = get_plan_limits(email)
    if not plan_info:
        log.error(f"No plan found for {email}, skipping PDF report.")
        log_security_event(
            event_type="pdf_skipped",
            email=email,
            details="No plan found"
        )
        return {"status": "skipped", "reason": "No plan", "email": email}

    plan_name = plan_info.get("plan", "FREE").upper()
    # --- ENFORCE PLAN GATING FOR PDF FEATURE & PDF QUOTA ---
    # PDF access: custom_pdf_briefings_frequency must be set (not None/False/empty) and pdf_reports_per_month quota must be > 0 (if set)
    if not plan_info.get("pdf_reports_per_month", 0):
        log.info(f"Skipped {email} — plan '{plan_name}' not eligible for PDF (pdf_reports_per_month=0).")
        log_security_event(
            event_type="pdf_plan_denied",
            email=email,
            plan=plan_name,
            details="Plan not eligible for PDF (zero quota)"
        )
        return {"status": "skipped", "reason": "Plan not eligible", "email": email, "plan": plan_name}
    if not require_plan_feature(email, "custom_pdf_briefings_frequency"):
        log.info(f"Skipped {email} — plan '{plan_name}' not eligible for PDF (no custom_pdf_briefings_frequency).")
        log_security_event(
            event_type="pdf_plan_denied",
            email=email,
            plan=plan_name,
            details="Plan not eligible for PDF (no custom_pdf_briefings_frequency)"
        )
        return {"status": "skipped", "reason": "Plan not eligible", "email": email, "plan": plan_name}

    # Enforce PDF quota per plan
    allowed, reason = check_user_pdf_quota(email, plan_info)
    if not allowed:
        log.info(f"PDF quota denied for {email}: {reason}")
        log_security_event(
            event_type="pdf_quota_denied",
            email=email,
            plan=plan_name,
            details=reason
        )
        return {"status": "skipped", "reason": reason, "email": email, "plan": plan_name}

    try:
        alerts = get_clean_alerts(region=region, user_email=email, session_id="pdfreport")
        pdf_file = generate_pdf(email, alerts, plan_name, region=region)

        msg = MIMEMultipart("mixed")
        msg["From"] = SENDER_EMAIL
        msg["To"] = email
        msg["Subject"] = f"Sentinel AI Report — {plan_name} Plan"

        text = (
            f"Sentinel AI {plan_name} Plan - Daily Travel Safety Report\n"
            f"Please find your attached PDF report.\n"
            f"Stay safe and informed.\n"
            f"https://zikarisk.com\n"
        )
        html = f"""\
        <html>
          <body style="font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif; color: #222;">
            <h2 style="color: #ed0000;">Sentinel AI Daily Brief — {plan_name} Plan</h2>
            <p>Your PDF report is attached.<br>
               <b>Stay safe and informed.</b></p>
            <hr>
            <p style="font-size:90%;color:#666;">
              Powered by <a href="https://zikarisk.com" style="color:#ed0000;text-decoration:none;">Sentinel AI</a>
            </p>
          </body>
        </html>
        """
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text, "plain"))
        alt.attach(MIMEText(html, "html"))
        msg.attach(alt)

        with open(pdf_file, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(pdf_file))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_file)}"'
            msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        log.info(f"Report sent to {email} ({plan_name})")
        log_security_event(
            event_type="pdf_sent",
            email=email,
            plan=plan_name,
            details=f"PDF report sent for region {region}"
        )
        # Increment PDF usage for user (after successful send)
        increment_user_pdf_usage(email)
        result = {"status": "sent", "email": email, "plan": plan_name}
    except Exception as e:
        log.error(f"Failed to send report to {email}: {str(e)}")
        log_security_event(
            event_type="pdf_send_failed",
            email=email,
            plan=plan_name,
            details=str(e)
        )
        result = {"status": "error", "reason": str(e), "email": email, "plan": plan_name}
    finally:
        try:
            report_path = Path(pdf_file)
            if report_path.exists():
                report_path.unlink()
                log.info(f"Deleted temporary PDF file: {pdf_file}")
                log_security_event(
                    event_type="pdf_cleanup",
                    email=email,
                    details=f"Deleted PDF file {pdf_file}"
                )
        except Exception as cleanup_err:
            log.error(f"Failed to clean up PDF file {pdf_file}: {cleanup_err}")
            log_security_event(
                event_type="pdf_cleanup_failed",
                email=email,
                details=f"Cleanup error: {cleanup_err}"
            )
    return result

def send_daily_summaries():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from plan_utils import DATABASE_URL

    results = []
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT u.email, u.full_name, u.plan, u.region
            FROM users u
            JOIN plans p ON u.plan = p.name
            WHERE p.custom_pdf_briefings_frequency IS NOT NULL
              AND u.is_active = TRUE
              AND p.name != 'FREE'
        """)
        users = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"Error fetching users for daily summaries: {e}")
        log_security_event(
            event_type="daily_summaries_user_fetch_failed",
            details=str(e)
        )
        return []

    for user in users:
        email = user["email"]
        region = user.get("region", None)
        result = send_pdf_report(email=email, region=region)
        results.append(result)
    log.info(f"Batch summary: {results}")
    log_security_event(
        event_type="daily_summaries_sent",
        details=f"Results: {results}"
    )
    return results