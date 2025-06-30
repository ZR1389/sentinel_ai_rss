import requests
import os
from datetime import date

TOKEN = "7980684217:AAGs4kWNrFVpkvzU0GdsnIKZpI7kl_3NPBg"
CHAT_ID = "7081882584"
PDF_PATH = f"/Users/zikarakita/Desktop/daily-brief-{date.today().isoformat()}.pdf"

def send_pdf_document():
    if not os.path.exists(PDF_PATH):
        print(f"❌ PDF not found: {PDF_PATH}")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    with open(PDF_PATH, 'rb') as pdf_file:
        files = {'document': pdf_file}
        data = {
            'chat_id': CHAT_ID,
            'caption': f"📄 Sentinel AI Daily Brief — {date.today().isoformat()}"
        }

        try:
            response = requests.post(url, data=data, files=files, timeout=10)
            if response.ok:
                print("✅ PDF sent to Telegram")
            else:
                print("❌ Failed to send PDF:", response.status_code, response.text)
        except requests.exceptions.RequestException as e:
            print("❌ Telegram request failed:", e)

send_pdf_document()

