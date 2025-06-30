import requests
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        print(f"❌ PDF not found: {pdf_path}")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    with open(pdf_path, 'rb') as pdf_file:
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

