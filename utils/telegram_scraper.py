# telegram_scraper.py — OSINT ingestion (unmetered) • v2025-08-13
from __future__ import annotations
import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from core.config import CONFIG

from utils.db_utils import save_raw_alerts_to_db

logger = logging.getLogger("telegram_scraper")
logging.basicConfig(level=CONFIG.security.log_level)

# Feature gate: disabled by default
TELEGRAM_ENABLED = CONFIG.telegram.enabled

# Optional bounds / hygiene
MAX_MSG_AGE_DAYS = CONFIG.telegram.max_msg_age_days
BATCH_LIMIT = CONFIG.telegram.batch_limit

# Try import Telethon (recommended), else soft-disable
try:
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetHistoryRequest
    from telethon.tl.types import PeerChannel
    _HAVE_TELETHON = True
except Exception as e:
    logger.info("Telethon not available: %s", e)
    _HAVE_TELETHON = False


def _utc(dt) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo:
            return dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _today_utc() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_alert(ch_name: str, msg: Any) -> Optional[Dict[str, Any]]:
    """
    Convert a Telegram message into raw_alerts row (schema-aligned).
    """
    try:
        text = (getattr(msg, "message", None) or "").strip()
        if not text:
            return None

        published = getattr(msg, "date", None)
        if published:
            published = _utc(published).replace(tzinfo=None)  # store naive UTC per your schema

        title = text.split("\n", 1)[0][:140]
        link = None
        # Try to construct a t.me link if we have ids
        mid = getattr(msg, "id", None)
        if mid:
            link = f"https://t.me/{ch_name}/{mid}"

        return {
            "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"tg:{ch_name}:{mid or uuid.uuid4()}")),
            "title": title,
            "summary": text[:2000],
            "en_snippet": None,  # advisor/threat engine will fill gpt_summary later
            "link": link,
            "source": f"telegram:{ch_name}",
            "published": published,
            "region": None,
            "country": None,
            "city": None,
            "tags": ["telegram","osint"],
            "language": "en",    # or attempt language detect in risk_shared if you want
            "ingested_at": datetime.utcnow(),
        }
    except Exception as e:
        logger.debug("coerce_alert failed: %s", e)
        return None


async def ingest_telegram_channels_to_db(channels: List[str], limit: int = BATCH_LIMIT, write_to_db: bool = True) -> Dict[str, Any]:
    """
    Async entry: scrapes recent messages from channels into raw_alerts (unmetered).
    """
    if not TELEGRAM_ENABLED:
        return {"ok": False, "reason": "TELEGRAM_ENABLED is false", "count": 0}

    if not _HAVE_TELETHON:
        return {"ok": False, "reason": "telethon not installed", "count": 0}

    api_id = CONFIG.telegram.api_id
    api_hash = CONFIG.telegram.api_hash
    session = CONFIG.telegram.session

    if not api_id or not api_hash:
        return {"ok": False, "reason": "TELEGRAM_API_ID/TELEGRAM_API_HASH missing", "count": 0}

    client = TelegramClient(session, int(api_id), api_hash)
    await client.start()

    max_age = _today_utc() - timedelta(days=MAX_MSG_AGE_DAYS)
    harvested: List[Dict[str, Any]] = []

    for ch in (channels or []):
        try:
            entity = await client.get_entity(ch)
            # simple page pull
            history = await client(GetHistoryRequest(
                peer=entity, limit=min(limit, BATCH_LIMIT), offset_date=None,
                offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0
            ))
            for msg in history.messages:
                dt = getattr(msg, "date", None)
                if dt and _utc(dt) < max_age:
                    continue
                alert = _coerce_alert(getattr(entity, 'username', ch).lower(), msg)
                if alert:
                    harvested.append(alert)
        except Exception as e:
            logger.warning("Channel '%s' fetch failed: %s", ch, e)

    await client.disconnect()

    wrote = 0
    if write_to_db and harvested:
        wrote = save_raw_alerts_to_db(harvested)

    return {"ok": True, "count": wrote if write_to_db else len(harvested), "preview": harvested[:3]}
