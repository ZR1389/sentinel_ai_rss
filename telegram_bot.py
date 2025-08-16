# telegram_bot.py — links a Telegram user to your account via /start <token>
from __future__ import annotations
import os
import base64
import logging
import psycopg2
from telethon import TelegramClient, events

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("telegram_bot")

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

if not (API_ID and API_HASH and BOT_TOKEN and DATABASE_URL):
    raise SystemExit("Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_BOT_TOKEN / DATABASE_URL")

def save_link(email_b64: str, chat_id: int, username: str | None):
    """Persist mapping (user_email -> chat_id, handle)."""
    pad = '=' * (-len(email_b64) % 4)  # fix base64 padding
    email = base64.urlsafe_b64decode(email_b64 + pad).decode().strip().lower()
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO telegram_links (user_email, chat_id, handle)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_email) DO UPDATE
            SET chat_id = EXCLUDED.chat_id,
                handle  = EXCLUDED.handle
        """, (email, str(chat_id), username))
        conn.commit()
    logger.info("Linked %s -> chat_id=%s handle=%s", email, chat_id, username)

# Start Telethon bot client
client = TelegramClient("sentinel_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@client.on(events.NewMessage(pattern=r"^/start(?:\s+(.*))?$"))
async def on_start(event: events.NewMessage.Event):
    """
    Expect /start <token> where token is urlsafe base64 of the user's email.
    Your backend should send users to https://t.me/<bot>?start=<token>
    """
    token = (event.pattern_match.group(1) or "").strip()
    if not token:
        await event.respond(
            "Hi! To link your account, please click the 'Connect Telegram' button in your dashboard."
        )
        return

    try:
        sender = await event.get_sender()
        username = (getattr(sender, "username", None) or "").strip() or None
        save_link(token, event.chat_id, username)
        await event.respond("✅ Telegram linked. You’ll now receive incident alerts here.")
    except Exception as e:
        logger.exception("Link failed")
        await event.respond("❌ Linking failed. Please try again from your dashboard.")

def main():
    logger.info("Bot running. Waiting for /start tokens…")
    client.run_until_disconnected()

if __name__ == "__main__":
    main()
