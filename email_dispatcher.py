from fpdf import FPDF
from datetime import date
from threat_scorer import assess_threat_level
from rss_processor import get_clean_alerts
from plan_rules import PLAN_RULES
import json
import os
from dotenv import load_dotenv
import smtplib
import ssl
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from chat_handler import get_plan
import re
import logging

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
SMTP_PORT = int(os.getenv("SMTP_PORT"))

def sanitize_filename(email):
    # Remove dangerous/special chars for filesystem
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", email)

def generate_pdf(email, alerts, plan, region=None):
    class PDF(FPDF):
        def header(self):
            heading = f"Sentinel AI Daily Brief — {plan.upper()} — {date.today().isoformat()}"
            self.set_font(FONT_FAMILY, "B", 16)
            self.set_text_color(237, 0, 0)
            self.cell(0, 10, heading, ln=True, align='C')
            self.ln(2)
            # Subheading with metadata
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

    # Score and truncate alerts for PDF
    scored_alerts = []
    for alert in alerts[:PDF_ALERT_LIMIT]:
        level = assess_threat_level(f"{alert['title']}: {alert['summary']}")
        scored_alerts.append({
            "title": alert["title"],
            "summary": alert["summary"],
            "source": alert["source"],
            "link": alert["link"],
            "level": level
        })

    pdf = PDF()
    pdf.add_font(FONT_FAMILY, "", FONT_PATH, uni=True)
    pdf.add_font(FONT_FAMILY, "B", FONT_PATH, uni=True)
    pdf.add_font(FONT_FAMILY, "I", FONT_PATH, uni=True)

    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.chapter_body(scored_alerts)

    safe_email = sanitize_filename(email)
    filename = f"report_{safe_email}_{date.today().isoformat()}.pdf"
    pdf.output(filename)
    log.info(f"PDF report generated: {filename} for {email}")
    return filename

def send_pdf_report(email, plan, region=None):
    plan_norm = plan.upper() if isinstance(plan, str) else "FREE"
    if not PLAN_RULES.get(plan_norm, {}).get("pdf", False):
        log.info(f"Skipped {email} — plan '{plan_norm}' not eligible for PDF.")
        return {"status": "skipped", "reason": "Plan not eligible", "email": email, "plan": plan_norm}

    alerts = get_clean_alerts()
    pdf_file = generate_pdf(email, alerts, plan, region=region)

    # --- Compose email with HTML and plain text ---
    msg = MIMEMultipart("mixed")
    msg["From"] = SENDER_EMAIL
    msg["To"] = email
    msg["Subject"] = f"Sentinel AI Report — {plan_norm} Plan"

    # Plain text body
    text = (
        f"Sentinel AI {plan_norm} Plan - Daily Travel Safety Report\n"
        f"Please find your attached PDF report.\n"
        f"Stay safe and informed.\n"
        f"https://zikarisk.com\n"
    )

    # HTML body
    html = f"""\
    <html>
      <body style="font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif; color: #222;">
        <h2 style="color: #ed0000;">Sentinel AI Daily Brief — {plan_norm} Plan</h2>
        <p>Your PDF report is attached.<br>
           <b>Stay safe and informed.</b></p>
        <hr>
        <p style="font-size:90%;color:#666;">
          Powered by <a href="https://zikarisk.com" style="color:#ed0000;text-decoration:none;">Sentinel AI</a>
        </p>
      </body>
    </html>
    """
    # Attach multipart/alternative (plain + html)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain"))
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)

    try:
        with open(pdf_file, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(pdf_file))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_file)}"'
            msg.attach(part)

        # Secure SMTP context
        context = ssl.create_default_context()
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls(context=context)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        log.info(f"Report sent to {email} ({plan_norm})")
        result = {"status": "sent", "email": email, "plan": plan_norm}
    except Exception as e:
        log.error(f"Failed to send report to {email}: {str(e)}")
        result = {"status": "error", "reason": str(e), "email": email, "plan": plan_norm}
    finally:
        report_path = Path(pdf_file)
        if report_path.exists():
            report_path.unlink()
            log.info(f"Deleted temporary PDF file: {pdf_file}")
    return result

def send_daily_summaries():
    with open("clients.json", "r") as f:
        clients = json.load(f)

    results = []
    for client in clients:
        email = client["email"]
        plan = client.get("plan", "FREE")
        region = client.get("region", None)
        plan_norm = plan.upper() if isinstance(plan, str) else "FREE"
        result = send_pdf_report(email=email, plan=plan_norm, region=region)
        results.append(result)
    log.info(f"Batch summary: {results}")
    return results