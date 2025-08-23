# rss_processor.py — Keyword-filtered ingest with fulltext fallback • v2025-08-23 (polished, strict keywording, production-ready)

from __future__ import annotations
import os, re, time, hashlib, contextlib, asyncio, json, sys
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Iterable, Tuple
from urllib.parse import urlparse

# .env loading (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ---- third-party (defensive imports) --------------------------------
import feedparser
import httpx

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 42
except Exception:
    def detect(_: str) -> str:  # type: ignore
        return "en"
    class DetectorFactory:       # type: ignore
        seed = 42

try:
    from unidecode import unidecode
except Exception:
    def unidecode(s: str) -> str:  # type: ignore
        return s

import logging
logger = logging.getLogger("rss_processor")
if not logger.handlers:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# ---------------------------- Geocode switch -------------------------
GEOCODE_ENABLED = (os.getenv("CITYUTILS_ENABLE_GEOCODE", "true").lower() in ("1","true","yes","y"))

try:
    from db_utils import save_raw_alerts_to_db, fetch_one, execute
except Exception as e:
    logger.error("db_utils import failed: %s", e)
    save_raw_alerts_to_db = None
    fetch_one = None
    execute = None

try:
    from city_utils import get_city_coords as _cu_get_city_coords
    from city_utils import fuzzy_match_city as _cu_fuzzy_match_city
    from city_utils import normalize_city as _cu_normalize_city
except Exception:
    _cu_get_city_coords = None
    _cu_fuzzy_match_city = None
    _cu_normalize_city = None

def _titlecase(s: str) -> str:
    return " ".join(p.capitalize() for p in (s or "").split())

def _safe_norm_city_country(city_like: str) -> Tuple[Optional[str], Optional[str]]:
    if not city_like:
        return None, None
    raw = (city_like or "").strip()
    if "," in raw:
        c, _, k = raw.partition(",")
        return _titlecase(c.strip()), _titlecase(k.strip()) if k.strip() else None
    return _titlecase(raw), None

def fuzzy_match_city(text: str) -> Optional[str]:
    if not text or _cu_fuzzy_match_city is None:
        return None
    try:
        return _cu_fuzzy_match_city(text)
    except Exception:
        return None

def normalize_city(city_like: str) -> Tuple[Optional[str], Optional[str]]:
    if not city_like:
        return (None, None)
    if not GEOCODE_ENABLED or _cu_normalize_city is None:
        return _safe_norm_city_country(city_like)
    try:
        return _cu_normalize_city(city_like)
    except Exception:
        return _safe_norm_city_country(city_like)

def get_city_coords(city: Optional[str], country: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if (not GEOCODE_ENABLED) or (not city) or (_cu_get_city_coords is None):
        return (None, None)
    try:
        return _cu_get_city_coords(city, country)
    except Exception:
        return (None, None)

# ---- fallback DB writer (used if db_utils is unavailable) ----------
if save_raw_alerts_to_db is None:
    try:
        import psycopg  # psycopg3
    except Exception as e:
        psycopg = None
        logger.error("psycopg not available for fallback DB writes: %s", e)

    def save_raw_alerts_to_db(alerts: list[dict]) -> int:
        dsn = os.getenv("DATABASE_URL")
        if not dsn or psycopg is None:
            logger.error("No DATABASE_URL or psycopg; cannot write alerts.")
            return 0

        cols = [
            "uuid","title","summary","en_snippet","link","source","published",
            "tags","region","country","city","language","latitude","longitude"
        ]
        placeholders = "%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s"
        sql = f"INSERT INTO raw_alerts ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT (uuid) DO NOTHING"

        wrote = 0
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    for a in alerts or []:
                        cur.execute(sql, [
                            a.get("uuid"),
                            a.get("title"),
                            a.get("summary"),
                            a.get("en_snippet"),
                            a.get("link"),
                            a.get("source"),
                            (a.get("published") or datetime.utcnow()),
                            json.dumps(a.get("tags") or []),
                            a.get("region"),
                            a.get("country"),
                            a.get("city"),
                            a.get("language") or "en",
                            a.get("latitude"),
                            a.get("longitude"),
                        ])
                        wrote += getattr(cur, "rowcount", 0) or 0
        except Exception as e:
            logger.exception("Fallback DB write failed: %s", e)
            return 0
        return wrote

# ---------------------------- Config ---------------------------------
DEFAULT_TIMEOUT        = float(os.getenv("RSS_TIMEOUT_SEC", "20"))
MAX_CONCURRENCY        = int(os.getenv("RSS_CONCURRENCY", "16"))
BATCH_LIMIT            = int(os.getenv("RSS_BATCH_LIMIT", "400"))

HOST_RATE_PER_SEC      = float(os.getenv("RSS_HOST_RATE_PER_SEC", "0.5"))
HOST_BURST             = int(os.getenv("RSS_HOST_BURST", "2"))

BACKOFF_BASE_MIN       = int(os.getenv("RSS_BACKOFF_BASE_MIN", "15"))
BACKOFF_MAX_MIN        = int(os.getenv("RSS_BACKOFF_MAX_MIN", "180"))
FAILURE_THRESHOLD      = int(os.getenv("RSS_BACKOFF_FAILS", "3"))

FRESHNESS_DAYS         = int(os.getenv("RSS_FRESHNESS_DAYS", "3"))

# Keyword filtering: ON by default (strict enforced)
RSS_FILTER_STRICT      = True

RSS_USE_FULLTEXT       = str(os.getenv("RSS_USE_FULLTEXT", "true")).lower() in ("1","true","yes","y")
ARTICLE_TIMEOUT_SEC    = float(os.getenv("RSS_FULLTEXT_TIMEOUT_SEC", "12"))
ARTICLE_MAX_BYTES      = int(os.getenv("RSS_FULLTEXT_MAX_BYTES", "800000"))
ARTICLE_MAX_CHARS      = int(os.getenv("RSS_FULLTEXT_MAX_CHARS", "20000"))
ARTICLE_CONCURRENCY    = int(os.getenv("RSS_FULLTEXT_CONCURRENCY", "8"))

if not GEOCODE_ENABLED:
    logger.info("CITYUTILS_ENABLE_GEOCODE is FALSE — geocoding disabled in rss_processor.")

# ---------------------- Keywords / Loading ---------------------------
FILTER_KEYWORDS_FALLBACK = [
    "protest","riot","clash","strike","unrest","shooting","stabbing","robbery","kidnap","kidnapping","extortion",
    "ied","vbied","explosion","bomb",
    "checkpoint","curfew","closure","detour","airport","border","rail","metro","highway","road",
    "substation","grid","pipeline","telecom","power outage",
    "ransomware","phishing","malware","breach","ddos","credential","zero-day","cve","surveillance","device check","spyware",
    "earthquake","flood","wildfire","hurricane","storm","heatwave","outbreak","epidemic","pandemic","cholera","dengue","covid","ebola",
]

def _normalize(s: str) -> str:
    if not s:
        return ""
    s = unidecode(s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _load_keywords() -> Tuple[List[str], str]:
    source_mode = (os.getenv("KEYWORDS_SOURCE", "merge") or "merge").lower()
    use_json = source_mode in ("merge", "json_only")
    use_risk = source_mode in ("merge", "risk_only")

    kws: List[str] = []
    seen: set[str] = set()

    if use_json:
        path = os.getenv("THREAT_KEYWORDS_PATH", "threat_keywords.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                base = data.get("keywords") or []
                if isinstance(base, list):
                    for k in base:
                        kk = _normalize(str(k))
                        if kk and kk not in seen:
                            seen.add(kk); kws.append(kk)
                translated = data.get("translated", {})
                if isinstance(translated, dict):
                    for _root, langmap in translated.items():
                        if not isinstance(langmap, dict):
                            continue
                        for _lang, lst in langmap.items():
                            if not isinstance(lst, list):
                                continue
                            for k in lst:
                                kk = _normalize(str(k))
                                if kk and kk not in seen:
                                    seen.add(kk); kws.append(kk)
            elif isinstance(data, list):
                for k in data:
                    kk = _normalize(str(k))
                    if kk and kk not in seen:
                        seen.add(kk); kws.append(kk)
        except Exception as e:
            logger.info("threat_keywords.json not loaded (%s); continuing", e)

    if use_risk:
        try:
            from risk_shared import CATEGORY_KEYWORDS, DOMAIN_KEYWORDS
            for lst in list(CATEGORY_KEYWORDS.values()) + list(DOMAIN_KEYWORDS.values()):
                for k in lst:
                    kk = _normalize(str(k))
                    if kk and kk not in seen:
                        seen.add(kk); kws.append(kk)
        except Exception:
            pass

    if not kws:
        kws = [_normalize(k) for k in FILTER_KEYWORDS_FALLBACK]

    return kws, source_mode

KEYWORDS, KEYWORDS_MODE = _load_keywords()
logger.info("Loaded %d keywords (mode=%s)", len(KEYWORDS), KEYWORDS_MODE)

def _kw_match(text: str) -> bool:
    t = _normalize(text)
    for kw in KEYWORDS:
        if kw in t:
            return True
    return False

# ---------------------- Catalog / Sources ----------------------------
try:
    from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS
except Exception:
    LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS = {}, {}, []

NATIVE_PRIORITY   = 10
FALLBACK_PRIORITY = 30
KIND_PRIORITY = {"native": NATIVE_PRIORITY, "env": NATIVE_PRIORITY, "fallback": FALLBACK_PRIORITY, "unknown": 999}

def _wrap_spec(url: str, priority: int, kind: str, tag: str = "") -> Dict[str, Any]:
    return {"url": url.strip(), "priority": priority, "kind": kind, "tag": tag}

def _build_native_specs() -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for city, urls in (LOCAL_FEEDS or {}).items():
        for u in (urls or []):
            specs.append(_wrap_spec(u, NATIVE_PRIORITY, "native", f"local:{city}"))
    for country, urls in (COUNTRY_FEEDS or {}).items():
        for u in (urls or []):
            specs.append(_wrap_spec(u, NATIVE_PRIORITY, "native", f"country:{country}"))
    for u in (GLOBAL_FEEDS or []):
        specs.append(_wrap_spec(u, NATIVE_PRIORITY, "native", "global"))
    return specs

def _load_env_feeds() -> List[str]:
    env = os.getenv("SENTINEL_FEEDS") or ""
    return [u.strip() for u in env.split(",") if u.strip()]

def _core_fallback_feeds() -> List[str]:
    return [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://www.france24.com/en/rss",
        "https://www.smartraveller.gov.au/countries/documents/index.rss",
    ]

def _coalesce_all_feed_specs(group_names: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    specs.extend(_build_native_specs())
    for u in _load_env_feeds():
        specs.append(_wrap_spec(u, NATIVE_PRIORITY, "env", "env"))
    for u in _core_fallback_feeds():
        specs.append(_wrap_spec(u, FALLBACK_PRIORITY, "fallback", "core"))
    specs.sort(key=lambda s: s.get("priority", 100))
    seen, out = set(), []
    for s in specs:
        cleaned = re.sub(r"[?#].*$", "", s["url"])
        if cleaned in seen: continue
        seen.add(cleaned); s["url"] = cleaned; out.append(s)
    return out

# ---------------------- Helpers -------------------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _uuid_for(source: str, title: str, link: str) -> str:
    return _sha(f"{source}|{title}|{link}")

def _safe_lang(text: str, default: str = "en") -> str:
    t = (text or "").strip()
    if not t: return default
    try: return detect(t[:1000]) or default
    except Exception: return default

def _first_sentence(text: str) -> str:
    t = (text or "").strip()
    if not t: return ""
    parts = re.split(r'(?<=[.!?。！？])\s+', t)
    return parts[0] if parts else t

def _normalize_summary(title: str, summary: str) -> str:
    return summary.strip() if summary and len(summary) >= 20 else (title or "").strip()

def _extract_source(url: str) -> str:
    try: return re.sub(r"^www\.", "", urlparse(url).netloc)
    except Exception: return "unknown"

def _parse_published(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            with contextlib.suppress(Exception):
                return datetime(*val[:6], tzinfo=timezone.utc)
    return _now_utc()

# ---------------------- Backoff / Health ----------------------------
def _host(url: str) -> str:
    with contextlib.suppress(Exception): return urlparse(url).netloc
    return "unknown"

def _db_fetch_one(q: str, args: tuple) -> Optional[tuple]:
    if fetch_one is None: return None
    try: return fetch_one(q, args)
    except Exception: return None

def _db_execute(q: str, args: tuple) -> None:
    if execute is None: return
    with contextlib.suppress(Exception): execute(q, args)

def _should_skip_by_backoff(url: str) -> bool:
    row = _db_fetch_one("SELECT backoff_until FROM feed_health WHERE feed_url=%s", (url,))
    if not row or not row[0]: return False
    try: return datetime.utcnow() < row[0]
    except Exception: return False

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

# ---------------------- Token bucket per host -----------------------
class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = max(rate_per_sec, 0.0001)
        self.capacity = max(burst, 1)
        self.tokens = float(self.capacity)
        self.updated = _now_utc().timestamp()
    async def acquire(self):
        now = _now_utc().timestamp()
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

# ---------------------- Fulltext extraction -------------------------
def _strip_html_basic(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

async def _fetch_article_fulltext(client: httpx.AsyncClient, url: str) -> str:
    if not RSS_USE_FULLTEXT or not url:
        return ""
    try:
        r = await client.get(url, timeout=ARTICLE_TIMEOUT_SEC)
        r.raise_for_status()
        html = r.text
        if len(html) > ARTICLE_MAX_BYTES:
            html = html[:ARTICLE_MAX_BYTES]
        try:
            import trafilatura
            extracted = trafilatura.extract(html, include_comments=False, favor_recall=True) or ""
            if extracted:
                return extracted[:ARTICLE_MAX_CHARS]
        except Exception:
            pass
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script","style","noscript"]): tag.decompose()
            txt = soup.get_text(separator=" ", strip=True)
            return txt[:ARTICLE_MAX_CHARS]
        except Exception:
            pass
        return _strip_html_basic(html)[:ARTICLE_MAX_CHARS]
    except Exception as e:
        logger.debug("Fulltext fetch failed for %s: %s", url, e)
        return ""

# ---------------------- Ingest core ---------------------------------
def _dedupe_batch(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set(); out = []
    for it in items:
        key = it.get("link") or it.get("title") or ""
        h = hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append(it)
    return out

def _extract_entries(feed_text: str, feed_url: str) -> Tuple[List[Dict[str, Any]], str]:
    fp = feedparser.parse(feed_text)
    entries = []
    source_url = fp.feed.get("link") if fp and fp.feed else feed_url
    for e in fp.entries or []:
        entries.append({
            "title": (e.get("title") or "").strip(),
            "summary": (e.get("summary") or e.get("description") or "").strip(),
            "link": (e.get("link") or feed_url or "").strip(),
            "published": _parse_published(e),
        })
    return entries, (source_url or feed_url)

async def _build_alert_from_entry(entry: Dict[str, Any], source_url: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)

    title = entry["title"]
    summary = _normalize_summary(title, entry["summary"])
    link = entry["link"]
    published = entry["published"] or _now_utc()
    if published and published < cutoff:
        return None

    source = _extract_source(source_url or link)

    text_blob = f"{title}\n{summary}"
    if not _kw_match(text_blob):
        fulltext = await _fetch_article_fulltext(client, link)
        if not fulltext:
            return None
        text_blob = f"{title}\n{summary}\n{fulltext}"
        if not _kw_match(text_blob):
            return None

    city = None; country = None
    try:
        guess_city = fuzzy_match_city(f"{title} {summary}") if _cu_fuzzy_match_city else None
        if guess_city:
            city, country = normalize_city(guess_city)
    except Exception:
        pass

    latitude = longitude = None
    if city and GEOCODE_ENABLED:
        with contextlib.suppress(Exception):
            latitude, longitude = get_city_coords(city, country)

    lang = _safe_lang(text_blob)
    uuid = _uuid_for(source, title, link)

    if fetch_one is not None:
        try:
            exists = fetch_one("SELECT 1 FROM raw_alerts WHERE uuid=%s", (uuid,))
            if exists:
                return None
        except Exception:
            pass

    snippet = _first_sentence(unidecode(summary))
    tags = _auto_tags(text_blob)

    return {
        "uuid": uuid,
        "title": title,
        "summary": summary,
        "en_snippet": snippet,
        "link": link,
        "source": source,
        "published": (published or _now_utc()).replace(tzinfo=None),
        "tags": tags,
        "region": None,
        "country": country,
        "city": city,
        "language": lang,
        "latitude": latitude,
        "longitude": longitude,
    }

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

# ---------------------- Top-level ingest ----------------------------
async def ingest_feeds(feed_specs: List[Dict[str, Any]], limit: int = BATCH_LIMIT) -> List[Dict[str, Any]]:
    if not feed_specs: return []
    results_alerts: List[Dict[str, Any]] = []
    limits = httpx.Limits(max_connections=MAX_CONCURRENCY, max_keepalive_connections=MAX_CONCURRENCY)
    async with httpx.AsyncClient(follow_redirects=True, limits=limits) as client:
        async def _fetch_feed(spec):
            if _should_skip_by_backoff(spec["url"]): return None, spec
            await _bucket_for(spec["url"]).acquire()
            start = time.perf_counter()
            try:
                r = await client.get(spec["url"], timeout=DEFAULT_TIMEOUT)
                r.raise_for_status()
                txt = r.text
                _record_health(spec["url"], ok=True, latency_ms=(time.perf_counter()-start)*1000.0)
                return txt, spec
            except Exception as e:
                _record_health(spec["url"], ok=False, latency_ms=(time.perf_counter()-start)*1000.0, error=str(e))
                logger.warning("Feed fetch failed for %s: %s", spec["url"], e)
                return None, spec

        feed_results = await asyncio.gather(*[_fetch_feed(s) for s in feed_specs], return_exceptions=False)

        sem = asyncio.Semaphore(max(1, ARTICLE_CONCURRENCY))
        async def _process_entry(entry, source_url):
            async with sem:
                return await _build_alert_from_entry(entry, source_url, client)

        for txt, spec in feed_results:
            if not txt:
                continue
            entries, source_url = _extract_entries(txt, spec["url"])
            tasks = [asyncio.create_task(_process_entry(e, source_url)) for e in entries]
            for coro in asyncio.as_completed(tasks):
                res = await coro
                if res:
                    kind = spec.get("kind", "unknown"); tag = spec.get("tag", "")
                    res.setdefault("source_kind", kind)
                    res.setdefault("source_priority", KIND_PRIORITY.get(kind, 999))
                    if tag: res.setdefault("source_tag", tag)
                    results_alerts.append(res)
                    if len(results_alerts) >= limit:
                        break
            if len(results_alerts) >= limit:
                break

    return _dedupe_batch(results_alerts)[:limit]

async def ingest_all_feeds_to_db(
    group_names: Optional[List[str]] = None,
    limit: int = BATCH_LIMIT,
    write_to_db: bool = True
) -> Dict[str, Any]:
    start = time.time()
    specs = _coalesce_all_feed_specs(group_names)
    alerts = await ingest_feeds(specs, limit=limit)
    alerts = alerts[:limit]

    errors: List[str] = []
    wrote = 0
    if write_to_db:
        if save_raw_alerts_to_db is None:
            errors.append("DB writer unavailable: db_utils.save_raw_alerts_to_db import failed or DATABASE_URL not set")
        elif alerts:
            try:
                wrote = save_raw_alerts_to_db(alerts)
            except Exception as e:
                errors.append(f"DB write failed: {e}")
                logger.exception("DB write failed")
        else:
            logger.info("No alerts to write (count=0)")

    return {
        "ok": True,
        "count": len(alerts),
        "wrote": wrote,
        "feeds_used": len(specs),
        "elapsed_sec": round(time.time() - start, 2),
        "errors": errors,
        "sample": alerts[:5],
        "filter_strict": RSS_FILTER_STRICT,
        "use_fulltext": RSS_USE_FULLTEXT,
    }

# ---------------------- CLI -----------------------------------------

WRITE_TO_DB_DEFAULT = str(os.getenv("RSS_WRITE_TO_DB", "true")).lower() in ("1","true","yes","y")
FAIL_CLOSED = str(os.getenv("RSS_FAIL_CLOSED", "true")).lower() in ("1","true","yes","y")

if __name__ == "__main__":
    if not WRITE_TO_DB_DEFAULT and FAIL_CLOSED:
        raise SystemExit("Refusing to run with RSS_WRITE_TO_DB=false; set RSS_WRITE_TO_DB=true")

    if not WRITE_TO_DB_DEFAULT:
        logger.warning("RSS_WRITE_TO_DB is FALSE — raw_alerts will NOT be written. "
                       "Set RSS_WRITE_TO_DB=true to enable inserts into raw_alerts.")

    print("🔍 Running RSS processor…")
    try:
        res = asyncio.run(
            ingest_all_feeds_to_db(group_names=None, limit=BATCH_LIMIT, write_to_db=WRITE_TO_DB_DEFAULT)
        )
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        logger.exception("Fatal error in rss_processor")
        sys.exit(1)

    print(res)
    try:
        print(
            f"ok={res.get('ok')} count={res.get('count')} wrote={res.get('wrote')} "
            f"feeds={res.get('feeds_used')} elapsed={res.get('elapsed_sec')}s "
            f"errors={len(res.get('errors') or [])} "
            f"filter_strict={res.get('filter_strict')} fulltext={res.get('use_fulltext')}"
        )
    except Exception:
        pass

    if WRITE_TO_DB_DEFAULT and res.get("count", 0) > 0 and res.get("wrote", 0) == 0:
        logger.error("Alerts found but no rows written — investigate DB writer.")
        sys.exit(2)