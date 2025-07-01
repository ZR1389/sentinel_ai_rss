import os
import json
import smtplib
from fpdf import FPDF
from dotenv import load_dotenv
from datetime import date
from email.message import EmailMessage
from chat_handler import handle_user_query
from telegram_dispatcher import send_telegram_pdf

# ✅ Load environment
load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))

# ✅ PDF layout using fpdf2
class PDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Sentinel AI - Daily Threat Briefing", ln=True, align="C")
        self.set_font("Arial", "", 12)
        self.cell(0, 10, date.today().isoformat(), ln=True, align="C")
        self.ln(10)

    def add_toc(self, categorized_alerts):
        self.set_font("Arial", "B", 12)
        self.set_text_color(0, 0, 0)
        self.cell(0, 10, "Summary by Threat Level", ln=True)
        self.ln(2)

        for level in ["Critical", "High", "Moderate", "Low"]:
            if categorized_alerts[level]:
                color = {
                    "Critical": (255, 0, 0),
                    "High": (255, 102, 0),
                    "Moderate": (255, 165, 0),
                    "Low": (0, 128, 0)
                }[level]
                self.set_text_color(*color)
                self.set_font("Arial", "B", 11)
                self.cell(0, 8, f"• {level}: {len(categorized_alerts[level])} alert(s)", ln=True)

        self.set_text_color(0, 0, 0)
        self.set_font("Arial", "", 12)
        self.ln(5)

    def body(self, summary):
        self.set_font("Arial", "", 12)
        alerts = summary.strip().split("\n\n")
        categorized = {"Critical": [], "High": [], "Moderate": [], "Low": [], "Unknown": []}
        parsed_alerts = []

        for alert in alerts:
            lines = alert.strip().split("\n")
            content_lines = []
            threat_level = "Unknown"
            for line in lines:
                if line.startswith("Threat Level:"):
                    threat_level = line.replace("Threat Level:", "").strip()
                else:
                    content_lines.append(line)
            categorized.setdefault(threat_level, []).append(alert)
            parsed_alerts.append((threat_level, "\n".join(content_lines).strip()))

        self.add_toc(categorized)

        for threat_level, content in parsed_alerts:
            color = {
                "Critical": (255, 0, 0),
                "High": (255, 102, 0),
                "Moderate": (255, 165, 0),
                "Low": (0, 128, 0)
            }.get(threat_level, (0, 0, 0))

            self.set_text_color(*color)
            self.multi_cell(0, 10, content)
            self.ln(1)

            self.set_font("Arial", "B", 12)
            self.cell(0, 10, f"Threat Level: {threat_level}", ln=True)
            self.ln(4)

            self.set_font("Arial", "", 12)
            self.set_text_color(0, 0, 0)

# ✅ Used by /request_report route
def send_pdf_report(email, plan):
    os.makedirs("reports", exist_ok=True)

    print(f"⏳ Generating summary for {email} ({plan})...")
    summary = handle_user_query("status", email=email).get("reply", "")


    if not summary or summary.startswith("[Sentinel AI error]"):
        raise Exception("No summary generated.")

    pdf = PDF()
    pdf.add_page()
    pdf.body(summary)

    pdf_filename = f"{email.replace('@', '_')}_{date.today()}.pdf"
    pdf_path = os.path.join("reports", pdf_filename)
    pdf.output(pdf_path)

    msg = EmailMessage()
    msg["Subject"] = "Your Sentinel AI Daily Threat Brief"
    msg["From"] = SENDER_EMAIL
    msg["To"] = email
    msg.set_content("Attached is your personalized Sentinel AI threat report.")

    with open(pdf_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=pdf_filename)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp.send_message(msg)

    print(f"✅ Email sent to {email}")

    send_telegram_pdf(pdf_path)
    print(f"✅ Telegram sent for {email}")

# ✅ Used by cron jobs or dev calls
def send_daily_summaries():
    with open("clients.json", "r") as f:
        clients = json.load(f)

    for client in clients:
        try:
            send_pdf_report(client["email"], client["plan"])
        except Exception as e:
            print(f"❌ Error sending to {client['email']}: {e}")

# ✅ Export for main.py
__all__ = ["send_pdf_report", "send_daily_summaries"]
