import os
import json
import smtplib
from fpdf import FPDF
from dotenv import load_dotenv
from datetime import date
from email.message import EmailMessage
from chat_handler import handle_user_query, translate_text
from telegram_dispatcher import send_telegram_pdf

# ✅ Load environment
load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))

# ✅ Threat type filters by plan
THREAT_FILTERS = {
    "VIP": None,
    "PRO": {"Kidnapping", "Cyber", "Terrorism", "Protest", "Crime"},
    "FREE": {"Protest", "Crime"}
}

# ✅ PDF layout using fpdf2
class PDF(FPDF):
    def __init__(self, lang="en"):
        super().__init__()
        self.lang = lang

    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, translate_text("Sentinel AI - Daily Threat Briefing", self.lang), ln=True, align="C")
        self.set_font("Arial", "", 12)
        self.cell(0, 10, date.today().isoformat(), ln=True, align="C")
        self.ln(10)

    def body(self, summary, allowed_types=None):
        self.set_font("Arial", "", 12)
        alerts = summary.strip().split("\n\n")

        # Parse into type -> alert list
        by_type = {}
        for alert in alerts:
            lines = alert.strip().split("\n")
            current_type = "Unclassified"
            current_level = "Unknown"
            content_lines = []

            for line in lines:
                if line.startswith("🔸"):
                    current_type = line.replace("🔸", "").strip().split(" ")[0].title()
                elif line.startswith("Threat Level:"):
                    current_level = line.replace("Threat Level:", "").strip()
                else:
                    content_lines.append(line)

            # Apply plan filter
            if allowed_types is not None and current_type not in allowed_types:
                continue

            body_text = "\n".join(content_lines).strip()
            by_type.setdefault(current_type, []).append((current_level, body_text))

        # Sort and display
        for threat_type, entries in by_type.items():
            self.set_font("Arial", "B", 13)
            self.set_text_color(0, 0, 0)
            self.cell(0, 10, translate_text(f"{threat_type.upper()} ({len(entries)} alert(s))", self.lang), ln=True)
            self.ln(2)

            for threat_level, body in entries:
                color = {
                    "Critical": (255, 0, 0),
                    "High": (255, 102, 0),
                    "Moderate": (255, 165, 0),
                    "Low": (0, 128, 0)
                }.get(threat_level, (0, 0, 0))

                self.set_text_color(*color)
                self.multi_cell(0, 10, body)
                self.ln(1)

                self.set_font("Arial", "B", 12)
                translated_label = translate_text("Threat Level", self.lang)
                translated_level = translate_text(threat_level, self.lang)
                self.cell(0, 10, f"{translated_label}: {translated_level}", ln=True)
                self.ln(4)

                self.set_font("Arial", "", 12)
                self.set_text_color(0, 0, 0)

# ✅ Used by /request_report or daily cron
def send_pdf_report(email, plan, lang="en"):
    os.makedirs("reports", exist_ok=True)

    print(f"⏳ Generating summary for {email} ({plan})...")
    summary = handle_user_query("status", email=email, lang=lang).get("reply", "")

    if not summary or summary.startswith("[Sentinel AI error]"):
        raise Exception("No summary generated.")

    allowed_types = THREAT_FILTERS.get(plan.upper())

    pdf = PDF(lang=lang)
    pdf.add_page()
    pdf.body(summary, allowed_types=allowed_types)

    pdf_filename = f"{email.replace('@', '_')}_{date.today()}.pdf"
    pdf_path = os.path.join("reports", pdf_filename)
    pdf.output(pdf_path)

    msg = EmailMessage()
    msg["Subject"] = translate_text("Your Sentinel AI Daily Threat Brief", lang)
    msg["From"] = SENDER_EMAIL
    msg["To"] = email
    msg.set_content(translate_text("Attached is your personalized Sentinel AI threat report.", lang))

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
            lang = client.get("lang", "en")
            send_pdf_report(client["email"], client["plan"], lang=lang)
        except Exception as e:
            print(f"❌ Error sending to {client['email']}: {e}")

# ✅ Export for main.py
__all__ = ["send_pdf_report", "send_daily_summaries"]
