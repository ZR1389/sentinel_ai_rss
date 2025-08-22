# rss_processor.py — Catalog ingest with health/backoff & throttling • v2025-08-20
# Backend job (NOT metered): fetch feeds -> parse -> filter -> dedupe -> raw_alerts
# Extras: per-host token bucket, feed health table support, geo infer via city_utils
# Note: SaaS-grade: now filters old news (timedelta, recalculated per batch), and skips DB duplicates by uuid.

from __future__ import annotations
import os
import asyncio
import contextlib
import hashlib
import json
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Iterable, Tuple
from urllib.parse import urlparse

import feedparser
import httpx
from langdetect import detect, DetectorFactory
from unidecode import unidecode
from dotenv import load_dotenv

# --- project deps
try:
    from db_utils import save_raw_alerts_to_db, fetch_one, execute
except Exception:  # soft-fallbacks so the script still runs
    save_raw_alerts_to_db = None
    fetch_one = None
    execute = None

# --- geocoding function ---
try:
    # get_city_coords(city, country) -> (lat, lon) or (None, None)
    from city_utils import get_city_coords
except Exception:
    def get_city_coords(city, country):
        # fallback, always None
        return None, None

# Deterministic language detection
DetectorFactory.seed = 42
load_dotenv()

# ---------------------------- Config ----------------------------
DEFAULT_TIMEOUT   = float(os.getenv("RSS_TIMEOUT_SEC", "20"))
MAX_CONCURRENCY   = int(os.getenv("RSS_CONCURRENCY", "16"))
BATCH_LIMIT       = int(os.getenv("RSS_BATCH_LIMIT", "400"))
HOST_RATE_PER_SEC = float(os.getenv("RSS_HOST_RATE_PER_SEC", "0.5"))  # ~1 req / 2s
HOST_BURST        = int(os.getenv("RSS_HOST_BURST", "2"))

# Backoff config
BACKOFF_BASE_MIN   = int(os.getenv("RSS_BACKOFF_BASE_MIN", "15"))
BACKOFF_MAX_MIN    = int(os.getenv("RSS_BACKOFF_MAX_MIN", "180"))
FAILURE_THRESHOLD  = int(os.getenv("RSS_BACKOFF_FAILS", "3"))

# Freshness cutoff for news items (in days): SaaS best practice = 3
FRESHNESS_DAYS = int(os.getenv("RSS_FRESHNESS_DAYS", "3"))
# Don't set FRESHNESS_CUTOFF at module load—calculate it per batch in _parse_feed_text

# Try to import canonical keywords from risk_shared
FILTER_KEYWORDS_FALLBACK = [
    # physical/civil
    "protest","riot","clash","strike","unrest","shooting","stabbing","robbery","kidnap","kidnapping","extortion",
    # terror
    "ied","vbied","explosion","bomb",
    # travel/mobility/infra
    "checkpoint","curfew","closure","detour","airport","border","rail","metro","highway","road",
    "substation","grid","pipeline","telecom","power outage",
    # cyber/digital
    "ransomware","phishing","malware","breach","ddos","credential","zero-day","cve","surveillance","device check","spyware",
    # environmental/epidemic
    "earthquake","flood","wildfire","hurricane","storm","heatwave","outbreak","epidemic","pandemic","cholera","dengue","covid","ebola",
]
try:
    from risk_shared import DOMAIN_KEYWORDS, CATEGORY_KEYWORDS
    _MERGED = list(DOMAIN_KEYWORDS.values()) + list(CATEGORY_KEYWORDS.values())
    FILTER_KEYWORDS = sorted({kw for lst in _MERGED for kw in lst})
except Exception:
    FILTER_KEYWORDS = FILTER_KEYWORDS_FALLBACK

# ---------------------------- Catalog imports & priorities ----------------------------
try:
    from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS
except Exception:
    LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS = {}, {}, []

# Priority knobs (lower number = higher priority)
NATIVE_PRIORITY   = 10
FALLBACK_PRIORITY = 30

# Map item kind -> numeric preference for de-dupe
KIND_PRIORITY = {
    "native": NATIVE_PRIORITY,
    "env": NATIVE_PRIORITY,
    "fallback": FALLBACK_PRIORITY,
    "unknown": 999,
}

# ---------------------------- Utils ----------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _uuid_for(source: str, title: str, link: str) -> str:
    return _sha(f"{source}|{title}|{link}")

def _safe_lang(text: str, default: str = "en") -> str:
    t = (text or "").strip()
    if not t:
        return default
    try:
        return detect(t[:1000]) or default
    except Exception:
        return default

def _first_sentence(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    parts = re.split(r'(?<=[.!?。！？])\s+', t)
    return parts[0] if parts else t

def _normalize_summary(title: str, summary: str) -> str:
    return summary.strip() if summary and len(summary) >= 20 else (title or "").strip()

def _filter_relevance(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in FILTER_KEYWORDS)

def _extract_source(url: str) -> str:
    try:
        return re.sub(r"^www\.", "", urlparse(url).netloc)
    except Exception:
        return "unknown"

def _parse_published(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            with contextlib.suppress(Exception):
                return datetime(*val[:6], tzinfo=timezone.utc)
    return _now_utc()

# ----------------------- Feed health / Backoff -----------------------
def _host(url: str) -> str:
    with contextlib.suppress(Exception):
        return urlparse(url).netloc
    return "unknown"

def _db_fetch_one(q: str, args: tuple) -> Optional[tuple]:
    if fetch_one is None:
        return None
    try:
        return fetch_one(q, args)
    except Exception:
        return None

def _db_execute(q: str, args: tuple) -> None:
    if execute is None:
        return
    with contextlib.suppress(Exception):
        execute(q, args)

def _should_skip_by_backoff(url: str) -> bool:
    row = _db_fetch_one("SELECT backoff_until FROM feed_health WHERE feed_url=%s", (url,))
    if not row or not row[0]:
        return False
    try:
        return datetime.utcnow() < row[0]
    except Exception:
        return False

def _record_health(url: str, ok: bool, latency_ms: float, error: Optional[str] = None):
    host = _host(url)
    if ok:
        _db_execute("""
        INSERT INTO feed_health (feed_url, host, last_status, last_error, last_ok, last_checked, ok_count, avg_latency_ms, consecutive_fail, backoff_until)
        VALUES (%s,%s,'ok',NULL,NOW(),NOW(),1,%s,0,NULL)
        ON CONFLICT (feed_url) DO UPDATE SET
          last_status='ok',
          last_error=NULL,
          last_ok=NOW(),
          last_checked=NOW(),
          ok_count=feed_health.ok_count+1,
          consecutive_fail=0,
          avg_latency_ms = CASE WHEN feed_health.ok_count=0 THEN EXCLUDED.avg_latency_ms
                                ELSE (feed_health.avg_latency_ms*feed_health.ok_count + EXCLUDED.avg_latency_ms) / (feed_health.ok_count+1)
                           END,
          host=EXCLUDED.host
        """, (url, host, float(latency_ms)))
    else:
        _db_execute("""
        INSERT INTO feed_health (feed_url, host, last_status, last_error, last_checked, error_count, consecutive_fail)
        VALUES (%s,%s,'error',%s,NOW(),1,1)
        ON CONFLICT (feed_url) DO UPDATE SET
          last_status='error',
          last_error=EXCLUDED.last_error,
          last_checked=NOW(),
          error_count=feed_health.error_count+1,
          consecutive_fail=feed_health.consecutive_fail+1,
          host=EXCLUDED.host
        """, (url, host, (error or "")[:240]))

        _db_execute("""
        UPDATE feed_health
           SET backoff_until = CASE
               WHEN consecutive_fail >= %s
               THEN NOW() + (LEAST(%s, %s * POWER(2, GREATEST(0, consecutive_fail - %s))) || ' minutes')::interval
               ELSE NULL
           END
         WHERE feed_url=%s
        """, (FAILURE_THRESHOLD, BACKOFF_MAX_MIN, BACKOFF_BASE_MIN, FAILURE_THRESHOLD, url))

# ----------------------- Token bucket per host -----------------------
class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = max(rate_per_sec, 0.0001)
        self.capacity = max(burst, 1)
        self.tokens = float(self.capacity)
        self.updated = _now_utc().timestamp()

    async def acquire(self):
        now = _now_utc().timestamp()
        # refill
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1.0:
            await asyncio.sleep((1.0 - self.tokens) / self.rate)
            self.tokens = 0.0
        self.tokens -= 1.0

HOST_BUCKETS: Dict[str, TokenBucket] = {}

def _bucket_for(url: str) -> TokenBucket:
    host = _host(url)
    if host not in HOST_BUCKETS:
        HOST_BUCKETS[host] = TokenBucket(HOST_RATE_PER_SEC, HOST_BURST)
    return HOST_BUCKETS[host]

# ----------------------- Legacy env helpers (kept) -----------------------
def _env_groups() -> List[str]:
    env = os.getenv("SENTINEL_FEED_GROUPS") or ""
    return [g.strip() for g in env.split(",") if g.strip()]

def _load_env_feeds() -> List[str]:
    env = os.getenv("SENTINEL_FEEDS") or ""
    return [u.strip() for u in env.split(",") if u.strip()]

def _load_catalog(group_names: Optional[Iterable[str]] = None) -> List[str]:
    feeds: List[str] = []
    try:
        import feeds_catalog as fc
        if hasattr(fc, "get_all_feeds"):
            feeds.extend(list(getattr(fc, "get_all_feeds")() or []))
        if group_names and hasattr(fc, "FEED_GROUPS"):
            groups = getattr(fc, "FEED_GROUPS") or {}
            for g in group_names:
                feeds.extend(groups.get(g, []))
        if hasattr(fc, "FEEDS"):
            feeds.extend(list(getattr(fc, "FEEDS") or []))
    except Exception:
        pass
    return feeds

def _core_fallback_feeds() -> List[str]:
    # Lowest-priority global safety nets
    return [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://www.france24.com/en/rss",
        "https://www.scmp.com/rss/5/feed/",
        "https://www.smartraveller.gov.au/countries/documents/index.rss",
    ]

# ----------------------- Feed spec builders -----------------------
def _wrap_spec(url: str, priority: int, kind: str, tag: str = "") -> Dict[str, Any]:
    return {"url": url.strip(), "priority": priority, "kind": kind, "tag": tag}

def _build_native_specs() -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    # 1) LOCAL_FEEDS: dict[str, list[str]]
    for city, urls in (LOCAL_FEEDS or {}).items():
        for u in (urls or []):
            specs.append(_wrap_spec(u, NATIVE_PRIORITY, "native", f"local:{city}"))

    # 2) COUNTRY_FEEDS: dict[str, list[str]]
    for country, urls in (COUNTRY_FEEDS or {}).items():
        for u in (urls or []):
            specs.append(_wrap_spec(u, NATIVE_PRIORITY, "native", f"country:{country}"))

    # 3) GLOBAL_FEEDS: list[str]
    for u in (GLOBAL_FEEDS or []):
        specs.append(_wrap_spec(u, NATIVE_PRIORITY, "native", "global"))
    return specs

def _coalesce_all_feed_specs(group_names: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []

    # 1–3) Native catalog
    specs.extend(_build_native_specs())

    # 4) Env-provided feeds (user knows best)
    for u in _load_env_feeds():
        specs.append(_wrap_spec(u, NATIVE_PRIORITY, "env", "env"))

    # 5) Core fallbacks (lowest)
    for u in _core_fallback_feeds():
        specs.append(_wrap_spec(u, FALLBACK_PRIORITY, "fallback", "core"))

    # Sort by priority (stable), then dedupe by cleaned URL (first wins)
    specs.sort(key=lambda s: s.get("priority", 100))
    seen = set()
    out: List[Dict[str, Any]] = []
    for s in specs:
        u = s["url"]
        cleaned = re.sub(r"[?#].*$", "", u)
        if cleaned in seen:
            continue
        seen.add(cleaned)
        s["url"] = cleaned
        out.append(s)
    return out

def _coalesce_all_feed_urls(group_names: Optional[Iterable[str]] = None) -> List[str]:
    specs = _coalesce_all_feed_specs(group_names)
    return [s["url"] for s in specs]

# ----------------------- Parsing & tagging -----------------------
def _auto_tags(text: str) -> List[str]:
    t = (text or "").lower()
    tags: List[str] = []
    pairs = {
        "cyber_it": ["ransomware","phishing","malware","breach","ddos","credential","cve","zero-day","exploit","vpn","mfa"],
        "civil_unrest": ["protest","riot","clash","strike","looting","roadblock"],
        "physical_safety": ["shooting","stabbing","robbery","assault","kidnap","kidnapping","murder","attack"],
        "travel_mobility": ["checkpoint","curfew","closure","detour","airport","border","rail","metro","road","highway","port"],
        "infrastructure_utilities": ["substation","grid","pipeline","telecom","fiber","power outage","blackout"],
        "environmental_hazards": ["earthquake","flood","wildfire","hurricane","storm","heatwave","landslide"],
        "public_health_epidemic": ["outbreak","epidemic","pandemic","cholera","dengue","covid","ebola"],
        "terrorism": ["ied","vbied","explosion","bomb","suicide"],
        "digital_privacy_surveillance": ["surveillance","device check","spyware","pegasus","imsi","stingray","biometric"],
        "legal_regulatory": ["visa","immigration","border control","ban","restriction","curfew","checkpoint"],
    }
    for tag, kws in pairs.items():
        if any(k in t for k in kws):
            tags.append(tag)
    return tags

def _infer_location(title: str, summary: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        from city_utils import fuzzy_match_city, normalize_city
        text = f"{title} {summary}"
        city = fuzzy_match_city(text)
        if city:
            city_norm, country = normalize_city(city)
            return city_norm, country
    except Exception:
        pass
    return None, None

def _parse_feed_text(text: str, feed_url: str) -> List[Dict[str, Any]]:
    FRESHNESS_CUTOFF = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)  # <-- PATCHED: always current
    fp = feedparser.parse(text)
    out: List[Dict[str, Any]] = []
    for e in fp.entries:
        title = (e.get("title") or "").strip()
        summary = (e.get("summary") or e.get("description") or "").strip()
        link = (e.get("link") or feed_url or "").strip()
        published = _parse_published(e)
        source_url = (fp.feed.get("link") or link or feed_url or "").strip()
        source = _extract_source(source_url or link)

        if not title and not summary:
            continue

        summary = _normalize_summary(title, summary)
        snippet = _first_sentence(unidecode(summary))
        text_blob = f"{title}\n{summary}"

        if not _filter_relevance(text_blob):
            continue

        # --------- PATCH: always up-to-date SaaS freshness filter ---------
        if published < FRESHNESS_CUTOFF:
            continue  # skip old item

        city, country = _infer_location(title, summary)
        lang = _safe_lang(text_blob)
        uuid = _uuid_for(source, title, link)
        tags = _auto_tags(text_blob)

        # --------- Geocode: get latitude/longitude ---------
        latitude, longitude = None, None
        if city and country:
            try:
                latitude, longitude = get_city_coords(city, country)
            except Exception:
                latitude, longitude = None, None

        # --------- DB-level deduplication ---------
        if fetch_one is not None:
            exists = fetch_one("SELECT 1 FROM raw_alerts WHERE uuid=%s", (uuid,))
            if exists:
                continue  # already ingested in db

        out.append({
            "uuid": uuid,
            "title": title,
            "summary": summary,
            "en_snippet": snippet,
            "link": link,
            "source": source,
            "published": (published or _now_utc()).replace(tzinfo=None),  # store UTC-naive
            "tags": tags,
            "region": None,
            "country": country,
            "city": city,
            "language": lang,
            "latitude": latitude,
            "longitude": longitude,
        })
    return out

# ----------------------- Fetch & ingest -----------------------
async def _fetch_text(client: httpx.AsyncClient, url: str) -> Optional[str]:
    if _should_skip_by_backoff(url):
        return None
    await _bucket_for(url).acquire()
    start = time.perf_counter()
    try:
        r = await client.get(url, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        text = r.text
        _record_health(url, ok=True, latency_ms=(time.perf_counter()-start)*1000.0)
        return text
    except Exception as e:
        _record_health(url, ok=False, latency_ms=(time.perf_counter()-start)*1000.0, error=str(e))
        return None

async def ingest_feeds(feed_urls_or_specs: List[Any], limit: int = BATCH_LIMIT) -> List[Dict[str, Any]]:
    if not feed_urls_or_specs:
        return []
    slice_n = max(1, limit)
    specs: List[Dict[str, Any]] = []
    if feed_urls_or_specs and isinstance(feed_urls_or_specs[0], dict):
        specs = feed_urls_or_specs[:slice_n]
    else:
        specs = [{"url": u, "priority": 999, "kind": "unknown", "tag": ""} for u in feed_urls_or_specs[:slice_n]]

    results_alerts: List[Dict[str, Any]] = []
    limits = httpx.Limits(max_connections=MAX_CONCURRENCY, max_keepalive_connections=MAX_CONCURRENCY)
    async with httpx.AsyncClient(follow_redirects=True, limits=limits) as client:
        tasks = [_fetch_text(client, s["url"]) for s in specs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for spec, res in zip(specs, results):
            if isinstance(res, Exception) or not res:
                continue
            parsed = _parse_feed_text(res, feed_url=spec["url"])
            kind = spec.get("kind", "unknown")
            tag  = spec.get("tag", "")
            src_pri = KIND_PRIORITY.get(kind, 999)
            for it in parsed:
                it.setdefault("source_kind", kind)
                it.setdefault("source_priority", src_pri)
                if tag:
                    it.setdefault("source_tag", tag)
            results_alerts.extend(parsed)
    return _dedupe(results_alerts)

def _dedupe(alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_hash: Dict[str, Dict[str, Any]] = {}

    def published_dt(a: Dict[str, Any]) -> datetime:
        return a.get("published") or _now_utc()

    def pri(a: Dict[str, Any]) -> int:
        return int(a.get("source_priority", 999))

    for a in alerts:
        key = _sha(((a.get("title") or "") + "|" + (a.get("summary") or "")).lower())
        prev = by_hash.get(key)
        if not prev:
            by_hash[key] = a
            continue
        if pri(a) < pri(prev):
            by_hash[key] = a
        elif pri(a) == pri(prev) and published_dt(a) > published_dt(prev):
            by_hash[key] = a
    return list(by_hash.values())

# ----------------------- Top-level ingest -----------------------
async def ingest_all_feeds_to_db(
    group_names: Optional[List[str]] = None,
    limit: int = BATCH_LIMIT,
    write_to_db: bool = True
) -> Dict[str, Any]:
    specs = _coalesce_all_feed_specs(group_names)
    alerts = await ingest_feeds(specs, limit=limit)
    alerts = alerts[:limit]
    if write_to_db and alerts and save_raw_alerts_to_db:
        save_raw_alerts_to_db(alerts)
    return {"count": len(alerts), "feeds_used": len(specs), "sample": alerts[:8]}

# ----------------------- CLI -----------------------
if __name__ == "__main__":
    print("🔍 Running RSS processor (native-first + health/backoff)...")
    loop = asyncio.get_event_loop()
    res = loop.run_until_complete(ingest_all_feeds_to_db(group_names=None, limit=BATCH_LIMIT, write_to_db=False))
    print(f"Fetched {res['count']} alerts from {res['feeds_used']} feeds (sample {len(res['sample'])}).")