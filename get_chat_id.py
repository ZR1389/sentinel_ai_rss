# get_chat_id.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set in .env")
    exit()

try:
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    print("✅ Telegram updates received:")
    print(data)

    if "result" in data and len(data["result"]) > 0:
        for update in data["result"]:
            chat = update.get("message", {}).get("chat", {})
            if chat:
                print(f"📩 Chat ID: {chat.get('id')} | Username: {chat.get('username')}")
    else:
        print("ℹ️ No chat messages yet. Send a message to the bot first.")

except requests.RequestException as e:
    print(f"❌ Error: {e}")
