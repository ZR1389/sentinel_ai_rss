import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Or load from clients.json if dynamic

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    response = requests.post(url, data=payload)
    if response.ok:
        print("✅ Telegram message sent.")
    else:
        print(f"❌ Failed to send Telegram message: {response.text}")

def send_telegram_pdf(file_path):
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    with open(file_path, "rb") as doc:
        files = {"document": doc}
        data = {"chat_id": CHAT_ID}
        response = requests.post(url, data=data, files=files)
        if response.ok:
            print("✅ PDF sent via Telegram.")
        else:
            print(f"❌ Failed to send PDF: {response.text}")
