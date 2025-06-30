import os
import json
import smtplib
from fpdf import FPDF
from dotenv import load_dotenv
from datetime import date
from email.message import EmailMessage
from chat_handler import generate_threat_summary

# ✅ Load environment
load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))

# ✅ Load client plans
with open("clients.json") as f:
    clients = json.load(f)

# ✅ PDF layout
class PDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Sentinel AI – Daily Threat Briefing", ln=True, align="C")
        self.set_font("Arial", "", 12)
        self.cell(0, 10, date.today().isoformat(), ln=True, align="C")
        self.ln(10)

    def body(self, summary):
        self.set_font("Arial", "", 12)
        self.multi_cell(0, 10, summary)

# ✅ Main dispatcher
def send_daily_summaries():
    os.makedirs("reports", exist_ok=True)

    for client in clients:
        email = client["email"]
        plan = client["plan"]

        print(f"⏳ Generating summary for {email} ({plan})...")
        summary = generate_threat_summary("Show global threat alerts", user_plan=plan)

        if not summary or summary.startswith("[Sentinel AI error]"):
            print(f"⚠️ Skipping {email} — No summary generated.")
            continue

        # Generate and save PDF
        pdf = PDF()
        pdf.add_page()
        pdf.body(summary)

        pdf_filename = f"{email.replace('@', '_')}_{date.today()}.pdf"
        pdf_path = os.path.join("reports", pdf_filename)
        pdf.output(pdf_path)

        # Compose email
        msg = EmailMessage()
        msg["Subject"] = "Your Sentinel AI Daily Threat Brief"
        msg["From"] = SENDER_EMAIL
        msg["To"] = email
        msg.set_content("Attached is your personalized Sentinel AI threat report.")

        with open(pdf_path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="pdf",
                filename=pdf_filename
            )

        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
                smtp.starttls()
                smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
                smtp.send_message(msg)
            print(f"✅ Email sent to {email}")
        except Exception as e:
            print(f"❌ Failed to send to {email} — {e}")

if __name__ == "__main__":
    send_daily_summaries()



