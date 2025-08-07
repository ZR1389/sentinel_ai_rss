import os
import re
import json
import asyncio
import httpx
import feedparser
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from dotenv import load_dotenv
from hashlib import sha256
from pathlib import Path
from unidecode import unidecode
import difflib
from langdetect import detect

from db_utils import save_raw_alerts_to_db
from db_utils import save_region_trend
from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS

with open('fcdo_country_feeds.json', 'r', encoding='utf-8') as f:
    FCDO_FEEDS = json.load(f)

with open('threat_keywords.json', 'r', encoding='utf-8') as f:
    keywords_data = json.load(f)
    THREAT_KEYWORDS = keywords_data["keywords"]
    TRANSLATED_KEYWORDS = keywords_data["translated"]

load_dotenv()

from telegram_scraper import scrape_telegram_messages
from translation_utils import translate_snippet

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    logger.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    logger.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

def json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

KEYWORD_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in THREAT_KEYWORDS) + r')\b',
    re.IGNORECASE
)

def first_sentence(text):
    sentences = re.split(r'(?<=[.!?。！？\n])\s+', text.strip())
    return sentences[0] if sentences else text

def any_multilingual_keyword(text, lang, TRANSLATED_KEYWORDS):
    text = text.lower()
    for threat, lang_map in TRANSLATED_KEYWORDS.items():
        roots = lang_map.get(lang, [])
        for root in roots:
            if root in text:
                return threat
    return None

def safe_detect_lang(text, default="en"):
    try:
        if len(text.strip()) < 10:
            return default
        return detect(text)
    except Exception:
        return default

NORMALIZED_LOCAL_FEEDS = {unidecode(city).lower().strip(): v for city, v in LOCAL_FEEDS.items()}

def get_feed_for_city(city):
    if not city:
        return None
    city_key = unidecode(city).lower().strip()
    match = difflib.get_close_matches(city_key, NORMALIZED_LOCAL_FEEDS.keys(), n=1, cutoff=0.8)
    if match:
        return NORMALIZED_LOCAL_FEEDS[match[0]]
    return None

def get_feed_for_location(region=None, city=None, topic=None):
    region_key = region.strip().title() if region else None
    city_feeds = get_feed_for_city(city)
    if city_feeds:
        logger.info("Using LOCAL feed(s) for city match.")
        return city_feeds
    if region_key and region_key in FCDO_FEEDS:
        logger.info("Using FCDO region feed.")
        return [FCDO_FEEDS[region_key]]
    if topic and topic.lower() == "cyber":
        try:
            from feeds_catalog import CYBER_FEEDS
            return CYBER_FEEDS
        except ImportError:
            pass
    region_key_lower = region.lower().strip() if region else None
    if region_key_lower and region_key_lower in COUNTRY_FEEDS:
        logger.info("Using COUNTRY feed.")
        return COUNTRY_FEEDS[region_key_lower]
    logger.info("Using GLOBAL feed(s) as fallback.")
    return GLOBAL_FEEDS

def normalize_timestamp(ts):
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        return ts.isoformat()
    if isinstance(ts, (int, float)):
        return datetime.utcfromtimestamp(ts).replace(tzinfo=timezone.utc).isoformat()
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        except Exception:
            try:
                import email.utils
                parsed = email.utils.parsedate_to_datetime(ts)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                else:
                    parsed = parsed.astimezone(timezone.utc)
                return parsed.isoformat()
            except Exception:
                return ts
    return None

def extract_keywords(text):
    raw_matches = []
    normalized_matches = []
    text_lower = text.lower()
    for k in THREAT_KEYWORDS:
        if re.search(rf'\b{re.escape(k)}\b', text_lower):
            raw_matches.append(k)
    normalized_matches = [k.lower() for k in raw_matches]
    return raw_matches, normalized_matches

def generate_series_id(region, keywords, timestamp):
    region = region or "unknown"
    keywords = sorted([k.lower() for k in (keywords or [])])
    try:
        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elif isinstance(timestamp, datetime):
            dt = timestamp
        else:
            dt = datetime.utcnow()
        day_str = dt.strftime("%Y-%m-%d")
    except Exception:
        day_str = "unknown"
    base = f"{region.lower().strip()}|{'-'.join(keywords)}|{day_str}"
    return sha256(base.encode("utf-8")).hexdigest()

def group_alerts_by_cluster(alerts, time_window_hours=48):
    clusters = {}
    cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
    for alert in alerts:
        published = alert.get("published")
        norm_time = normalize_timestamp(published)
        try:
            dt = datetime.fromisoformat(norm_time.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.utcnow()
        if dt < cutoff:
            continue
        cluster_id = alert.get("series_id")
        if not cluster_id:
            continue
        clusters.setdefault(cluster_id, []).append(alert)
    return clusters

def compute_trend_tracker(alerts, time_unit="week"):
    trend = {}
    for alert in alerts:
        city = alert.get("city", "unknown")
        published = alert.get("published")
        norm_time = normalize_timestamp(published)
        try:
            dt = datetime.fromisoformat(norm_time.replace("Z", "+00:00"))
        except Exception:
            continue
        if time_unit == "week":
            key = dt.strftime("%Y-W%U")
        elif time_unit == "day":
            key = dt.strftime("%Y-%m-%d")
        else:
            key = "other"
        trend.setdefault(city, {})
        trend[city][key] = trend[city].get(key, 0) + 1
    return trend

async def ingest_all_feeds_to_db(
    region=None, topic=None, city=None, limit=1000, summarize=False,
    llm_location_filter=True, use_telegram=False, write_to_db=True
):
    alerts = []
    seen = set()
    region_str = str(region).strip() if region else None
    topic_str = str(topic).lower() if isinstance(topic, str) and topic else "all"
    city_str = str(city).strip() if city else None

    feeds = get_feed_for_location(region=region_str, city=city_str, topic=topic_str)
    if not feeds:
        logger.info("⚠️ No feeds found for the given location/topic.")
        return []

    results = await asyncio.gather(*(fetch_feed_async(url) for url in feeds))

    telegram = []
    if use_telegram:
        try:
            telegram = scrape_telegram_messages(region=region_str, city=city_str, topic=topic_str, limit=limit)
            logger.info(f"Loaded {len(telegram)} alerts from Telegram OSINT.")
        except Exception as e:
            logger.warning(f"Telegram scraping failed: {e}")

    for feed, source_url in results:
        if not feed or 'entries' not in feed:
            continue
        source_domain = urlparse(source_url).netloc.replace("www.", "")
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            subtitle = first_sentence(summary)
            search_text = f"{title}. {subtitle}".lower()
            link = entry.get("link", "").strip()
            published_raw = entry.get("published", "")
            published = normalize_timestamp(published_raw)

            lang = safe_detect_lang(search_text)
            threat_match = any_multilingual_keyword(search_text, lang, TRANSLATED_KEYWORDS)
            english_match = KEYWORD_PATTERN.search(search_text)
            if not (threat_match or english_match):
                continue

            snippet = f"{title}. {summary}".strip()
            if lang != "en":
                en_snippet = translate_snippet(snippet, lang)
            else:
                en_snippet = snippet

            dedupe_key = sha256(f"{title}:{subtitle}".encode("utf-8")).hexdigest()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            raw_keywords, processed_keywords = extract_keywords(search_text)
            series_id = generate_series_id(region_str, raw_keywords, published)
            alert = {
                "uuid": dedupe_key,
                "series_id": series_id,
                "title": title,
                "summary": summary,
                "en_snippet": en_snippet,
                "link": link,
                "source": source_domain,
                "published": published,
                "region": region_str,
                "country": None,
                "city": city_str,
                "ingested_at": normalize_timestamp(datetime.utcnow()),
                "tags": raw_keywords,
                "processed_keywords": processed_keywords,
                "incident_series": series_id,
            }

            alerts.append(alert)
            if len(alerts) >= limit:
                logger.info(f"✅ Parsed {len(alerts)} alerts (limit reached for this run).")
                break
        if len(alerts) >= limit:
            break

    if use_telegram:
        for telegram_alert in telegram:
            dedupe_key = sha256((telegram_alert.get("title", "") + ":" + telegram_alert.get("summary", "")).encode("utf-8")).hexdigest()
            if dedupe_key in seen:
                continue
            telegram_alert['uuid'] = dedupe_key
            telegram_alert['source'] = "telegram"
            telegram_alert['ingested_at'] = normalize_timestamp(datetime.utcnow())
            raw_keywords, processed_keywords = extract_keywords(
                f"{telegram_alert.get('title','')} {telegram_alert.get('summary','')}"
            )
            telegram_alert['tags'] = raw_keywords
            telegram_alert['processed_keywords'] = processed_keywords
            series_id = generate_series_id(region_str, raw_keywords, telegram_alert.get("published", datetime.utcnow()))
            telegram_alert['series_id'] = series_id
            telegram_alert['incident_series'] = series_id
            alerts.append(telegram_alert)
            seen.add(dedupe_key)

    if llm_location_filter and (city_str or region_str):
        logger.info("🔍 Running LLM-based location relevance filtering is skipped by RSS processor (delegated to threat engine)...")

    if not alerts:
        logger.error("⚠️ No relevant alerts found for city/region. Will use fallback advisory.")
        return []

    clusters = group_alerts_by_cluster(alerts, time_window_hours=48)
    logger.info(f"🧩 Generated {len(clusters)} incident clusters (geo-temporal).")

    trend_tracker = compute_trend_tracker(alerts, time_unit="week")
    logger.info(f"📈 Threat counts by city/week: {json.dumps(trend_tracker, indent=2)}")

    try:
        for city, week_data in trend_tracker.items():
            for week, count in week_data.items():
                save_region_trend(
                    region=region_str or "",
                    city=city,
                    trend_window_start=week + "-1",
                    trend_window_end=week + "-7",
                    incident_count=count,
                    categories=None,
                )
        logger.info("Trend metadata stored in region_trends table.")
    except Exception as e:
        logger.error(f"Failed to store trend metadata: {e}")

    logger.info(f"✅ Parsed {len(alerts)} location-relevant alerts.")

    if write_to_db:
        try:
            logger.info(f"Writing {len(alerts)} raw alerts to raw_alerts table...")
            save_raw_alerts_to_db(alerts)
            logger.info("Raw alerts saved to DB successfully.")
        except Exception as e:
            logger.error(f"Failed to save raw alerts to DB: {e}")

    return {
        "alerts": alerts[:limit],
        "clusters": clusters,
        "trend_tracker": trend_tracker,
    }

async def fetch_feed_async(url, timeout=7, retries=3, backoff=1.5, max_backoff=60):
    attempt = 0
    current_backoff = backoff
    while attempt < retries:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=timeout)
                if response.status_code == 200:
                    logger.info(f"✅ Fetched: {url}")
                    return feedparser.parse(response.text), url
                elif response.status_code in [429, 503]:
                    current_backoff = min(current_backoff * 2, max_backoff)
                    logger.warning(f"⚠️ Throttled ({response.status_code}) by {url}; backing off for {current_backoff} seconds")
                    await asyncio.sleep(current_backoff)
                else:
                    logger.warning(f"⚠️ Feed returned {response.status_code}: {url}")
        except Exception as e:
            logger.warning(f"❌ Attempt {attempt + 1} failed for {url} — {e}")
        attempt += 1
        await asyncio.sleep(current_backoff)
    logger.warning(f"❌ Failed to fetch after {retries} retries: {url}")
    return None, url

if __name__ == "__main__":
    logger.info("🔍 Running standalone SYSTEM RSS processor (internal DB ingestion, NO user quotas)...")
    result = asyncio.run(ingest_all_feeds_to_db(region=None, limit=1000, summarize=True, use_telegram=False, write_to_db=True))
    alerts = result.get("alerts", [])
    clusters = result.get("clusters", {})
    trend_tracker = result.get("trend_tracker", {})
    if not alerts:
        logger.info("No relevant alerts found. (Fallback advisory skipped in system job.)")
    else:
        logger.info(f"Alerts processed: {len(alerts)}")
        logger.info(f"Incident clusters detected: {len(clusters)}")
        logger.info(f"Threat trend tracker: {json.dumps(trend_tracker, indent=2)}")
        for alert in alerts:
            logger.info(json.dumps(alert, indent=2, default=json_default))