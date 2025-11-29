# telegram_dispatcher.py — paid-only, unmetered push • v2025-08-13
from __future__ import annotations
import os
import logging
from typing import Optional
from core.config import CONFIG

logger = logging.getLogger("telegram_dispatcher")
logging.basicConfig(level=CONFIG.security.log_level)

TELEGRAM_PUSH_ENABLED = CONFIG.telegram.push_enabled

# Plan gate (no metering here)
try:
    from plan_utils import user_has_paid_plan as _is_paid
except Exception:
    def _is_paid(_email: str) -> bool:  # fallback denies if plan_utils missing
        return False

try:
    from telegram import Bot
    _HAVE_TG = True
except Exception as e:
    logger.info("python-telegram-bot not available: %s", e)
    _HAVE_TG = False

def send_telegram_message(user_email: str, chat_id: str, text: str, parse_mode: Optional[str] = None) -> bool:
    """
    Paid-only, opt-in push. Unmetered. Returns False if not allowed or disabled.
    """
    if not _is_paid(user_email):
        logger.debug("telegram push denied: user not on paid plan (%s)", user_email)
        return False
    if not TELEGRAM_PUSH_ENABLED or not _HAVE_TG:
        logger.debug("telegram push disabled or missing deps")
        return False

    token = CONFIG.telegram.bot_token
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN missing; skipping telegram push")
        return False

    try:
        bot = Bot(token=token)
        bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode or "HTML", disable_web_page_preview=True)
        return True
    except Exception as e:
        logger.error("send_telegram_message failed: %s", e)
        return False
