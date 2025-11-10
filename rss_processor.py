# rss_processor.py — Aggressive diagnostics, fetch, and ingest for production debugging
# v2025-08-24 PATCHED+COUNTRY+NO-BACKOFF+MATCHER (2025-08-31) + FULL
# - No backoff (ever)
# - Optional per-host throttle (can be fully disabled via HOST_THROTTLE_ENABLED=false)
# - Postgres geocode cache
# - Proper source_tag threading (local:city[, country] & country:country)
# - City→Country defaults for common cities
# - Reverse country from (lon,lat) via countries.geojson (no external deps)
# - NEW: Keyword/Co-occurrence matcher aligned with risk_shared + threat_keywords.json,
#        storing kw_match for Threat Scorer/Engine.
# - Content-first hybrid location extractor with normalization and provenance fields

from __future__ import annotations
import os, re, time, hashlib, contextlib, asyncio, json, sys, threading
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Iterable, Tuple
from urllib.parse import urlparse

# .env loading
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

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
logging.basicConfig(level=logging.DEBUG, force=True)
logger = logging.getLogger("rss_processor")

# Import refactored alert building components
from alert_builder_refactored import (
    AlertMetadata, LocationResult, ContentValidator,
    SourceTagParser, LocationExtractor, AlertBuilder,
    build_alert_from_entry_v2
)

# Import proper batch state management (eliminates function attribute anti-pattern)
from batch_state_manager import get_batch_state_manager

# === Moonshot Location Batching (Using Proper State Management) ===
# ANTI-PATTERN FIXED: No longer using function attributes or module globals
# Old anti-pattern: _build_alert_from_entry._pending_batch_results
# Old anti-pattern: _PENDING_BATCH_RESULTS as module global
# New approach: Proper state management via BatchStateManager

_LOCATION_BATCH_THRESHOLD = int(os.getenv("MOONSHOT_LOCATION_BATCH_THRESHOLD", "10"))

# Legacy globals during transition (TODO: Remove after full migration)
_LOCATION_BATCH_BUFFER: List[Tuple[Dict[str, Any], str, str]] = []
_LOCATION_BATCH_LOCK = threading.Lock()

# Memory leak prevention constants
MAX_BUFFER_SIZE = int(os.getenv("MOONSHOT_MAX_BUFFER_SIZE", "1000"))
MAX_BUFFER_AGE_SECONDS = int(os.getenv("MOONSHOT_MAX_BUFFER_AGE", "3600"))  # 1 hour
MAX_BATCH_RETRIES = int(os.getenv("MOONSHOT_MAX_RETRIES", "3"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("MOONSHOT_CLEANUP_INTERVAL", "900"))  # 15 minutes
MAX_ALERT_BATCH_AGE_SECONDS = int(os.getenv("MOONSHOT_MAX_ALERT_BATCH_AGE", "7200"))  # 2 hours

# ANTI-PATTERN REMOVED: No longer using module-level globals for batch results  
# Old: _PENDING_BATCH_RESULTS: Dict[str, Dict] = {}
# Old: _PENDING_BATCH_RESULTS_LOCK = threading.Lock()
# New: Managed by BatchStateManager - proper encapsulation, thread-safety, testability

# Memory leak prevention tracking (legacy during transition)
_BUFFER_RETRY_COUNT: Dict[str, int] = {}
_BUFFER_TIMESTAMPS: Dict[str, float] = {}
_LAST_CLEANUP_TIME = time.time()
_BATCH_FAILURE_COUNT = 0

# -----------------------------------------------------------------------------
# basic normalizer (placed at top as requested)
def _normalize(s: str) -> str:
    if not s:
        return ""
    try:
        s2 = unidecode(s)
    except Exception:
        s2 = s
    s2 = s2.lower()
    s2 = re.sub(r"\s+", " ", s2).strip()
    return s2

# -----------------------------------------------------------------------------
# HYBRID LOCATION EXTRACTION MODULE
# -----------------------------------------------------------------------------

# ---------------------------- spaCy NER Setup -------------------------
try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
    logger.info("[NER] spaCy model loaded successfully")
    SPACY_AVAILABLE = True
except Exception as e:
    logger.warning("[NER] spaCy not available: %s - falling back to keywords/LLM", e)
    nlp = None
    SPACY_AVAILABLE = False

# ---------------------------- Location Keywords Setup -------------------------
LOCATION_KEYWORDS = None
try:
    keywords_path = os.path.join(os.path.dirname(__file__), "location_keywords.json")
    with open(keywords_path, "r", encoding="utf-8") as f:
        LOCATION_KEYWORDS = json.load(f)
    logger.info("[KEYWORDS] Loaded %d countries, %d cities from location_keywords.json",
                len(LOCATION_KEYWORDS.get("countries", {})),
                len(LOCATION_KEYWORDS.get("cities", {})))
except Exception as e:
    logger.warning("[KEYWORDS] location_keywords.json not found: %s", e)
    LOCATION_KEYWORDS = {"countries": {}, "cities": {}, "regions": {}}

# ---------------------------- LLM Router for Location Extraction -------------------------
try:
    from llm_router import route_llm
    LLM_AVAILABLE = True
    logger.info("[LLM] LLM router available for location extraction fallback")
except Exception as e:
    logger.warning("[LLM] LLM router not available: %s", e)
    LLM_AVAILABLE = False
    route_llm = None

# ---------------------------- Country normalization helper -------------------------
def _normalize_country_name(raw: Optional[str]) -> Optional[str]:
    """
    Normalize a raw country token to a canonical name present in LOCATION_KEYWORDS
    or via pycountry. Returns canonical English country name or the original
    title-cased if no mapping found.
    """
    if not raw:
        return None
    s = _normalize(raw)
    try:
        # direct keyword mapping (location_keywords keys are normalized)
        if s in LOCATION_KEYWORDS.get("countries", {}):
            return LOCATION_KEYWORDS["countries"][s]
    except Exception:
        pass

    # try pycountry for aliases / codes / fuzzy
    try:
        import pycountry
        # try exact name
        try:
            c = pycountry.countries.get(name=raw)
            if c:
                return c.name
        except Exception:
            pass
        # alpha2
        try:
            c = pycountry.countries.get(alpha_2=(raw or "").upper())
            if c:
                return c.name
        except Exception:
            pass
        # alpha3
        try:
            c = pycountry.countries.get(alpha_3=(raw or "").upper())
            if c:
                return c.name
        except Exception:
            pass
        # fuzzy search
        try:
            res = pycountry.countries.search_fuzzy(raw)
            if res:
                return res[0].name
        except Exception:
            pass
    except Exception:
        # pycountry not installed or failed - fall back
        pass

    # fallback to titlecased raw
    return (raw or "").strip().title()

# ---------------------------- Map country -> region -------------------------
def _map_country_to_region(country: Optional[str]) -> Optional[str]:
    """Map a country to its geographic region (expects canonical country names)."""
    if not country:
        return None
    # simple region map (kept similar to prior mapping)
    region_map = {
        "Europe": [
            "Albania", "Andorra", "Austria", "Belarus", "Belgium", "Bosnia and Herzegovina",
            "Bulgaria", "Croatia", "Cyprus", "Czech Republic", "Denmark", "Estonia",
            "Finland", "France", "Germany", "Greece", "Hungary", "Iceland", "Ireland",
            "Italy", "Kosovo", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg",
            "Malta", "Moldova", "Monaco", "Montenegro", "Netherlands", "North Macedonia",
            "Norway", "Poland", "Portugal", "Romania", "Russia", "San Marino", "Serbia",
            "Slovakia", "Slovenia", "Spain", "Sweden", "Switzerland", "Ukraine",
            "United Kingdom", "Vatican City"
        ],
        "Asia": [
            "Afghanistan", "Armenia", "Azerbaijan", "Bahrain", "Bangladesh", "Bhutan",
            "Brunei", "Cambodia", "China", "Georgia", "India", "Indonesia", "Japan",
            "Jordan", "Kazakhstan", "Kuwait", "Kyrgyzstan", "Laos", "Lebanon", "Malaysia",
            "Maldives", "Mongolia", "Myanmar", "Nepal", "North Korea", "Oman", "Pakistan",
            "Palestine", "Philippines", "Qatar", "Saudi Arabia", "Singapore", "South Korea",
            "Sri Lanka", "Syria", "Taiwan", "Tajikistan", "Thailand", "Timor-Leste",
            "Turkey", "Turkmenistan", "United Arab Emirates", "Uzbekistan", "Vietnam", "Yemen"
        ],
        "Africa": [
            "Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cameroon",
            "Cape Verde", "Central African Republic", "Chad", "Comoros", "Democratic Republic of Congo",
            "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Ethiopia", "Gabon", "Gambia",
            "Ghana", "Guinea", "Guinea-Bissau", "Ivory Coast", "Kenya", "Lesotho", "Liberia",
            "Libya", "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco",
            "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Senegal", "Seychelles",
            "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania",
            "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe"
        ],
        "North America": ["Canada", "Mexico", "United States"],
        "Central America": ["Belize", "Costa Rica", "El Salvador", "Guatemala", "Honduras", "Nicaragua", "Panama"],
        "South America": ["Argentina", "Bolivia", "Brazil", "Chile", "Colombia", "Ecuador", "Guyana",
                          "Paraguay", "Peru", "Suriname", "Uruguay", "Venezuela"],
        "Oceania": ["Australia", "Fiji", "Kiribati", "Marshall Islands", "Micronesia", "Nauru",
                    "New Zealand", "Palau", "Papua New Guinea", "Samoa", "Solomon Islands",
                    "Tonga", "Tuvalu", "Vanuatu"],
        "Middle East": ["Bahrain", "Egypt", "Iran", "Iraq", "Israel", "Jordan", "Kuwait", "Lebanon",
                        "Oman", "Palestine", "Qatar", "Saudi Arabia", "Syria", "Turkey",
                        "United Arab Emirates", "Yemen"]
    }
    for region, countries in region_map.items():
        if country in countries:
            return region
    return None

# ---------------------------- NER / Keyword / LLM extractors -------------------------
# -----------------------------------------------------------------------------
# LEGACY LOCATION EXTRACTION FUNCTIONS - DEPRECATED
# These functions have been moved to location_service_consolidated.py
# Keep for backward compatibility but should not be used
# -----------------------------------------------------------------------------

# Deprecated: Use location_service_consolidated.detect_location() instead
def extract_location_hybrid(title: str, summary: str, source: str) -> Dict[str, Optional[str]]:
    """DEPRECATED: Use location_service_consolidated.detect_location() instead."""
    import warnings
    warnings.warn(
        "extract_location_hybrid is deprecated. Use location_service_consolidated.detect_location() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    # For backward compatibility, delegate to consolidated service
    try:
        from location_service_consolidated import detect_location
        result = detect_location(text=summary or "", title=title or "")
        return {
            "city": result.city,
            "country": result.country, 
            "region": result.region,
            "method": result.location_method,
            "confidence": result.location_confidence
        }
    except Exception as e:
        logger.error(f"Fallback location detection failed: {e}")
        return {"city": None, "country": None, "region": None, "method": "error", "confidence": "none"}

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
    from city_utils import normalize_city_country as _cu_normalize_city_country
except Exception:
    _cu_get_city_coords = None
    _cu_fuzzy_match_city = None
    _cu_normalize_city_country = None

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
    if not GEOCODE_ENABLED or _cu_normalize_city_country is None:
        return _safe_norm_city_country(city_like)
    try:
        return _cu_normalize_city_country(*_safe_norm_city_country(city_like))
    except Exception:
        return _safe_norm_city_country(city_like)

# ---------------------------- Postgres geocode cache -----------------
GEOCODE_CACHE_TTL_DAYS = int(os.getenv("GEOCODE_CACHE_TTL_DAYS", "180"))

def _geo_db_lookup(city: str, country: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if fetch_one is None:
        return None, None
    try:
        row = fetch_one(
            """
            SELECT lat, lon
            FROM geocode_cache
            WHERE city = %s
              AND COALESCE(country,'') = COALESCE(%s,'')
              AND updated_at > NOW() - (%s || ' days')::interval
            """,
            (city, country, str(GEOCODE_CACHE_TTL_DAYS)),
        )
        if row:
            lat, lon = row
            try:
                return (float(lat), float(lon))
            except Exception:
                return None, None
    except Exception as e:
        logger.debug("[rss_processor] geocode cache lookup failed for %s, %s: %s", city, country, e)
    return None, None

def _geo_db_store(city: str, country: Optional[str], lat: float, lon: float) -> None:
    if execute is None:
        return
    try:
        execute(
            """
            INSERT INTO geocode_cache (city, country, lat, lon, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (city, country) DO UPDATE SET
              lat = EXCLUDED.lat,
              lon = EXCLUDED.lon,
              updated_at = NOW()
            """,
            (city, country, float(lat), float(lon)),
        )
    except Exception as e:
        logger.debug("[rss_processor] geocode cache store failed for %s, %s: %s", city, country, e)

def get_city_coords(city: Optional[str], country: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if (not GEOCODE_ENABLED) or (not city) or (_cu_get_city_coords is None):
        return (None, None)
    try:
        lat, lon = _geo_db_lookup(city, country)
        if lat is not None and lon is not None:
            logger.debug("[rss_processor] geocode cache hit for %s, %s -> (%s,%s)", city, country, lat, lon)
            return lat, lon
        lat, lon = _cu_get_city_coords(city, country)
        if lat is not None and lon is not None:
            _geo_db_store(city, country, lat, lon)
        return lat, lon
    except Exception:
        return (None, None)

# ---- fallback DB writer (used if db_utils is unavailable) ----------
if save_raw_alerts_to_db is None:
    try:
        import psycopg
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
            "tags","region","country","city","location_method","location_confidence","language","latitude","longitude"
        ]
        placeholders = "%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s"
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
                            a.get("location_method"),
                            a.get("location_confidence"),
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

# Per-host throttle (NOT backoff). Can be disabled completely.
HOST_RATE_PER_SEC      = float(os.getenv("RSS_HOST_RATE_PER_SEC", "0.5"))
HOST_BURST             = int(os.getenv("RSS_HOST_BURST", "2"))
HOST_THROTTLE_ENABLED  = (os.getenv("HOST_THROTTLE_ENABLED", "true").lower() in ("1","true","yes","y"))

# Backoff knobs left for schema compatibility only (unused)
BACKOFF_BASE_MIN       = int(os.getenv("RSS_BACKOFF_BASE_MIN", "15"))
BACKOFF_MAX_MIN        = int(os.getenv("RSS_BACKOFF_MAX_MIN", "180"))
FAILURE_THRESHOLD      = int(os.getenv("RSS_BACKOFF_FAILS", "3"))

FRESHNESS_DAYS         = int(os.getenv("RSS_FRESHNESS_DAYS", "3"))

RSS_FILTER_STRICT      = True

RSS_USE_FULLTEXT       = str(os.getenv("RSS_USE_FULLTEXT", "true")).lower() in ("1","true","yes","y")
ARTICLE_TIMEOUT_SEC    = float(os.getenv("RSS_FULLTEXT_TIMEOUT_SEC", "12"))
ARTICLE_MAX_BYTES      = int(os.getenv("RSS_FULLTEXT_MAX_BYTES", "800000"))
ARTICLE_MAX_CHARS      = int(os.getenv("RSS_FULLTEXT_MAX_CHARS", "20000"))
ARTICLE_CONCURRENCY    = int(os.getenv("RSS_FULLTEXT_CONCURRENCY", "8"))

# NEW: toggle and window for co-occurrence matcher (aligned with risk_shared defaults)
RSS_ENABLE_COOCCURRENCE = str(os.getenv("RSS_ENABLE_COOCCURRENCE", "true")).lower() in ("1","true","yes","y")
RSS_COOC_WINDOW_TOKENS  = int(os.getenv("RSS_COOC_WINDOW_TOKENS", "15"))  # Aligned with risk_shared.py default
RSS_MIN_TEXT_LENGTH     = int(os.getenv("RSS_MIN_TEXT_LENGTH", "100"))  # New: minimum text length

if not GEOCODE_ENABLED:
    logger.info("CITYUTILS_ENABLE_GEOCODE is FALSE — geocoding disabled in rss_processor.")

FILTER_KEYWORDS_FALLBACK = [
    "protest","riot","clash","strike","unrest","shooting","stabbing","robbery","kidnap","kidnapping","extortion",
    "ied","vbied","explosion","bomb",
    "checkpoint","curfew","closure","detour","airport","border","rail","metro","highway","road",
    "substation","grid","pipeline","telecom","power outage",
    "ransomware","phishing","malware","breach","ddos","credential","zero-day","cve","surveillance","device check","spyware",
    "earthquake","flood","wildfire","hurricane","storm","heatwave","outbreak","epidemic","pandemic","cholera","dengue","covid","ebola"
]

# --------- Load threat keywords from JSON and/or risk_shared ----------
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

# --------- Build the co-occurrence matcher (aligned with risk_shared) ----------
MATCHER = None
try:
    from risk_shared import KeywordMatcher, build_default_matcher, get_all_keywords
    try:
        from risk_shared import BROAD_TERMS_DEFAULT as _BROAD_TERMS_DEFAULT
        from risk_shared import IMPACT_TERMS_DEFAULT as _IMPACT_TERMS_DEFAULT
    except Exception:
        _BROAD_TERMS_DEFAULT = []
        _IMPACT_TERMS_DEFAULT = []
    # Union JSON keywords with risk_shared canonical set to keep everything aligned
    merged_keywords: List[str] = []
    try:
        merged_set = set(KEYWORDS)
        try:
            for k in get_all_keywords():
                merged_set.add(_normalize(k))
        except Exception:
            pass
        merged_keywords = sorted(x for x in merged_set if x)
    except Exception:
        merged_keywords = KEYWORDS[:]

    if RSS_ENABLE_COOCCURRENCE:
        if _BROAD_TERMS_DEFAULT and _IMPACT_TERMS_DEFAULT:
            MATCHER = KeywordMatcher(
                keywords=merged_keywords,
                broad_terms=_BROAD_TERMS_DEFAULT,
                impact_terms=_IMPACT_TERMS_DEFAULT,
                window=RSS_COOC_WINDOW_TOKENS,
            )
        else:
            MATCHER = build_default_matcher(window=RSS_COOC_WINDOW_TOKENS)
except Exception as e:
    logger.debug("Matcher build failed; will use legacy contains-only filter: %s", e)
    MATCHER = None

def _kw_decide(title: str, text: str, lang: str = "en") -> Tuple[bool, Dict[str, Any]]:
    """
    Multi-tier filtering for quality alerts:
    1. Length check (min 100 chars)
    2. Strict co-occurrence (broad+impact within window)
    3. Fallback: require 2+ threat keywords
    Returns (hit, details).
    """
    combined = f"{title or ''}\n{text or ''}"
    if len(combined.strip()) < 100:
        return False, {"hit": False, "rule": "too_short", "matches": {}}

    blob_title = title or ""
    blob_text = text or ""

    if MATCHER is not None and RSS_ENABLE_COOCCURRENCE:
        try:
            res = MATCHER.decide(blob_text, title=blob_title)
            if res.hit:
                return True, {"hit": True, "rule": res.rule, "matches": res.matches, "tier": "strict"}
        except Exception as e:
            logger.debug("Matcher decide error, falling back: %s", e)

    t = _normalize(combined)
    matched_keywords = [kw for kw in KEYWORDS if kw in t]

    if len(matched_keywords) >= 2:
        return True, {
            "hit": True,
            "rule": "keyword_multi",
            "matches": {"keywords": matched_keywords[:5]},
            "tier": "fallback"
        }

    return False, {"hit": False, "rule": None, "matches": {}}

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
    if not t:
        return ""
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

# ------------- NO BACKOFF, EVER --------------
def _should_skip_by_backoff(url: str) -> bool:
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
        _db_execute("""UPDATE feed_health SET backoff_until=NULL WHERE feed_url=%s""", (url,))

class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = max(rate_per_sec, 0.0001)
        self.capacity = max(burst, 1)
        self.tokens = float(self.capacity)
        self.updated = _now_utc().timestamp()
    
    async def acquire(self):
        if not HOST_THROTTLE_ENABLED:
            return
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

# -------- City → Country defaults for common LOCAL_FEEDS cities -------
CITY_DEFAULTS = {
    "paris": "France",
    "sydney": "Australia",
    "delhi": "India",
    "singapore": "Singapore",
    "new york": "United States",
    "los angeles": "United States",
    "boston": "United States",
    "washington": "United States",
    "houston": "United States",
    "miami": "United States",
    "toronto": "Canada",
    "vancouver": "Canada",
    "montreal": "Canada",
    "mumbai": "India",
    "manila": "Philippines",
    "bangkok": "Thailand",
    "jakarta": "Indonesia",
    "nairobi": "Kenya",
    "cape town": "South Africa",
    "rome": "Italy",
    "berlin": "Germany",
    "vienna": "Austria",
    "zurich": "Switzerland",
    "amsterdam": "Netherlands",
    "hong kong": "Hong Kong",
    "tel aviv": "Israel",
    "tehran": "Iran, Islamic Republic of",
    "minsk": "Belarus",
}

def _apply_city_defaults(city: Optional[str], country: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if city and (not country or country.strip() == ""):
        ck = city.lower().strip()
        if ck in CITY_DEFAULTS:
            logger.debug("[rss_processor] CITY_DEFAULTS filled country: '%s' -> '%s'", city, CITY_DEFAULTS[ck])
            return city, CITY_DEFAULTS[ck]
    return city, country

# --- Reverse country from (lon,lat) using countries.geojson (no deps) ---
COUNTRIES_GEOJSON_PATH = os.getenv("COUNTRIES_GEOJSON_PATH")
_COUNTRIES_GJ = None
_POLY_INDEX: Optional[List[Tuple[str, List[List[Tuple[float,float]]]]]] = None
_BBOX_INDEX: Optional[List[Tuple[str, Tuple[float,float,float,float]]]] = None
_NE_NAME_FIELD = "ADMIN"

def _load_countries_gj() -> bool:
    global _COUNTRIES_GJ, _POLY_INDEX, _BBOX_INDEX
    if _POLY_INDEX is not None and _BBOX_INDEX is not None:
        return True
    if not COUNTRIES_GEOJSON_PATH or not os.path.exists(COUNTRIES_GEOJSON_PATH):
        logger.debug("[rss_processor] countries.geojson not configured or missing; reverse-country disabled.")
        return False
    try:
        with open(COUNTRIES_GEOJSON_PATH, "r", encoding="utf-8") as f:
            gj = json.load(f)
        feats = (gj or {}).get("features") or []
        polys: List[Tuple[str, List[List[Tuple[float,float]]]]] = []
        bboxes: List[Tuple[str, Tuple[float,float,float,float]]] = []

        def rings(geom):
            t = (geom or {}).get("type")
            coords = (geom or {}).get("coordinates")
            out = []
            if t == "Polygon":
                for ring in coords or []:
                    out.append([(float(x), float(y)) for x, y in ring])
            elif t == "MultiPolygon":
                for poly in coords or []:
                    for ring in poly:
                        out.append([(float(x), float(y)) for x, y in ring])
            return out

        def bbox(ring):
            xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
            return (min(xs), min(ys), max(xs), max(ys))

        for ft in feats:
            props = (ft or {}).get("properties") or {}
            name = str(props.get(_NE_NAME_FIELD) or "").strip()
            if not name:
                continue
            rs = rings((ft or {}).get("geometry") or {})
            if not rs:
                continue
            polys.append((name, rs))
            bboxes.append((name, bbox(rs[0])))

        _COUNTRIES_GJ = gj
        _POLY_INDEX = polys
        _BBOX_INDEX = bboxes
        logger.info("[rss_processor] Loaded countries.geojson (%d features) for reverse-country.", len(feats))
        logger.info("[rss_processor] COUNTRIES_GEOJSON_PATH=%s", COUNTRIES_GEOJSON_PATH)
        return True
    except Exception as e:
        logger.debug("[rss_processor] Failed to load countries.geojson: %s", e)
        _COUNTRIES_GJ = None; _POLY_INDEX = None; _BBOX_INDEX = None
        return False

def _point_in_ring(lon: float, lat: float, ring: List[Tuple[float,float]]) -> bool:
    x, y = lon, lat
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-16) + x1):
            inside = not inside
    return inside

def _reverse_country_from_lonlat(lon: Optional[float], lat: Optional[float]) -> Optional[str]:
    if lon is None or lat is None:
        return None
    if _POLY_INDEX is None or _BBOX_INDEX is None:
        if not _load_countries_gj():
            return None
    cands = []
    for name, (minx, miny, maxx, maxy) in _BBOX_INDEX or []:
        if (minx - 0.2) <= lon <= (maxx + 0.2) and (miny - 0.2) <= lat <= (maxy + 0.2):
            cands.append(name)
    if not cands:
        return None
    for name, rings in _POLY_INDEX or []:
        if name not in cands:
            continue
        inside = False
        for ring in rings:
            if _point_in_ring(lon, lat, ring):
                inside = not inside
        if inside:
            return name
    return None

# ---- Memory Leak Prevention Utilities ----

def _cleanup_stale_buffer_items():
    """Remove items from buffer that are too old"""
    global _LAST_CLEANUP_TIME
    current_time = time.time()
    removed_count = 0
    
    with _LOCATION_BATCH_LOCK:
        if current_time - _LAST_CLEANUP_TIME < CLEANUP_INTERVAL_SECONDS:
            return 0
            
        # Check each buffer item's timestamp
        new_buffer = []
        for item in _LOCATION_BATCH_BUFFER:
            alert, source_tag, uuid = item
            item_timestamp = _BUFFER_TIMESTAMPS.get(uuid, current_time)
            
            if current_time - item_timestamp <= MAX_BUFFER_AGE_SECONDS:
                new_buffer.append(item)
            else:
                removed_count += 1
                _BUFFER_TIMESTAMPS.pop(uuid, None)
                logger.warning(f"[Moonshot] Removed stale buffer item: {uuid}")
        
        _LOCATION_BATCH_BUFFER[:] = new_buffer
        _LAST_CLEANUP_TIME = current_time
    
    return removed_count

def _enforce_buffer_size_limit():
    """Remove oldest items if buffer exceeds size limit"""
    with _LOCATION_BATCH_LOCK:
        if len(_LOCATION_BATCH_BUFFER) <= MAX_BUFFER_SIZE:
            return 0
        
        # Sort by timestamp (oldest first) and remove excess
        buffer_with_timestamps = []
        for item in _LOCATION_BATCH_BUFFER:
            alert, source_tag, uuid = item
            timestamp = _BUFFER_TIMESTAMPS.get(uuid, time.time())
            buffer_with_timestamps.append((timestamp, item))
        
        buffer_with_timestamps.sort(key=lambda x: x[0])  # Sort by timestamp
        
        items_to_remove = len(_LOCATION_BATCH_BUFFER) - MAX_BUFFER_SIZE
        removed_count = 0
        
        # Remove oldest items
        for i in range(items_to_remove):
            timestamp, (alert, source_tag, uuid) = buffer_with_timestamps[i]
            _BUFFER_TIMESTAMPS.pop(uuid, None)
            removed_count += 1
            logger.warning(f"[Moonshot] Removed buffer item due to size limit: {uuid}")
        
        # Keep only the newest items
        _LOCATION_BATCH_BUFFER[:] = [item for _, item in buffer_with_timestamps[items_to_remove:]]
        
        return removed_count

def _should_retry_batch(batch_id: str) -> bool:
    """Check if batch processing should be retried"""
    current_count = _BUFFER_RETRY_COUNT.get(batch_id, 0)
    return current_count < MAX_BATCH_RETRIES

def _increment_retry_count(batch_id: str):
    """Increment retry count for a batch"""
    _BUFFER_RETRY_COUNT[batch_id] = _BUFFER_RETRY_COUNT.get(batch_id, 0) + 1

def _cleanup_failed_batches():
    """Remove tracking for permanently failed batches"""
    failed_batches = []
    for batch_id, count in _BUFFER_RETRY_COUNT.items():
        if count >= MAX_BATCH_RETRIES:
            failed_batches.append(batch_id)
    
    for batch_id in failed_batches:
        _BUFFER_RETRY_COUNT.pop(batch_id, None)
    
    return len(failed_batches)

def _clean_stale_batch_markers(alerts: List[Dict]) -> int:
    """Remove _batch_queued markers from alerts that are too old"""
    current_time = time.time()
    cleaned_count = 0
    
    for alert in alerts:
        if alert.get('_batch_queued'):
            # Use published time or current time as fallback
            try:
                alert_time = alert.get('published')
                if isinstance(alert_time, datetime):
                    alert_timestamp = alert_time.timestamp()
                else:
                    alert_timestamp = current_time
            except Exception:
                alert_timestamp = current_time
            
            # If alert is too old, remove batch marker and set fallback
            if current_time - alert_timestamp > MAX_ALERT_BATCH_AGE_SECONDS:
                alert.pop('_batch_queued', None)
                if alert.get('location_method') == 'batch_pending':
                    alert['location_method'] = 'fallback'
                    alert['location_confidence'] = 'none'
                    cleaned_count += 1
                    logger.warning(f"[Moonshot] Cleaned stale batch marker from alert: {alert.get('uuid', 'unknown')}")
    
    return cleaned_count

def _get_buffer_health_metrics() -> Dict[str, Any]:
    """Get metrics about buffer health for monitoring"""
    current_time = time.time()
    
    with _LOCATION_BATCH_LOCK:
        buffer_size = len(_LOCATION_BATCH_BUFFER)
        
        # Calculate age statistics
        ages = []
        for item in _LOCATION_BATCH_BUFFER:
            alert, source_tag, uuid = item
            timestamp = _BUFFER_TIMESTAMPS.get(uuid, current_time)
            ages.append(current_time - timestamp)
        
        avg_age = sum(ages) / len(ages) if ages else 0
        max_age = max(ages) if ages else 0
    
    # Count retry statistics
    total_retries = sum(_BUFFER_RETRY_COUNT.values())
    failed_batches = sum(1 for count in _BUFFER_RETRY_COUNT.values() if count >= MAX_BATCH_RETRIES)
    
    return {
        'buffer_size': buffer_size,
        'buffer_max_size': MAX_BUFFER_SIZE,
        'avg_item_age_seconds': avg_age,
        'max_item_age_seconds': max_age,
        'max_allowed_age_seconds': MAX_BUFFER_AGE_SECONDS,
        'total_retry_attempts': total_retries,
        'permanently_failed_batches': failed_batches,
        'buffer_utilization_percent': (buffer_size / MAX_BUFFER_SIZE) * 100 if MAX_BUFFER_SIZE > 0 else 0,
        'timestamp': current_time,
        'cleanup_interval': CLEANUP_INTERVAL_SECONDS,
        'max_retries': MAX_BATCH_RETRIES
    }
# ---------------------------- Moonshot Batch Functions ------

def _should_use_moonshot_for_location(entry: Dict, source_tag: str) -> bool:
    """
    Heuristic: Use Moonshot for ambiguous location cases.
    Checks if deterministic methods failed but location hints exist.
    """
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    
    try:
        from location_service_consolidated import is_location_ambiguous
        return is_location_ambiguous(text=summary, title=title)
    except Exception as e:
        logger.debug(f"[Moonshot] Ambiguous check fallback for {title[:50]}: {e}")
        
        # Fallback heuristics
        text = f"{title} {summary}".lower()
        
        # Look for location indicators without clear matches
        location_hints = any(word in text for word in [
            "in ", "at ", "from ", "near ", "police", "authorities", 
            "local", "regional", "government", "officials"
        ])
        
        # Check for travel/mobility domains where location is critical
        try:
            from risk_shared import detect_domains
            domains = detect_domains(text)
            if "travel_mobility" in domains or "civil_unrest" in domains:
                # Location is critical for these domains
                return True
        except Exception:
            # If risk_shared not available, use simpler fallback
            pass
        
        # Simple fallback: return true if location hints but no clear location from feed tag
        return location_hints and not source_tag.startswith(('local:', 'country:'))

# ---- Moonshot Batch Processing ----

async def _process_location_batch(client: httpx.AsyncClient) -> Dict[str, Dict]:
    """
    Process queued entries with a single Moonshot call using proper state management.
    
    ANTI-PATTERN FIXED: No longer uses module-level globals for batch storage.
    Uses BatchStateManager for thread-safe, testable state management.
    
    Returns: {uuid: location_data}
    """
    batch_state = get_batch_state_manager()
    
    # Extract all pending entries for processing
    batch_entries = batch_state.extract_buffer_entries()
    
    if not batch_entries:
        return {}

    logger.info(f"[Moonshot] Processing location batch of {len(batch_entries)} entries...")

    # Build concise prompt
    prompt = f"""Extract location (city, country, region) for each news item.
Return JSON array of objects with: city, country, region, confidence, alert_uuid.

--- ENTRIES ---\n\n"""

    for idx, batch_entry in enumerate(batch_entries):
        entry = batch_entry.entry
        source_tag = batch_entry.source_tag  
        uuid = batch_entry.uuid
        prompt += f"Item {idx}: {entry['title'][:120]} | Tag: {source_tag} | UUID: {uuid}\n"

    try:
        # Use Moonshot client
        from moonshot_client import MoonshotClient
        moonshot = MoonshotClient()

        response = await moonshot.acomplete(
            model="moonshot-v1-8k",  # 8k is sufficient for location
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1500
        )

        # Parse JSON array
        import re, json
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            results = json.loads(match.group())

            # Index by UUID
            location_map = {}
            for item in results:
                uuid = item.get('alert_uuid')
                if uuid:
                    location_map[uuid] = {
                        'city': item.get('city'),
                        'country': item.get('country'),
                        'region': item.get('region'),
                        'latitude': None,  # Will geocode later
                        'longitude': None,
                        'location_method': 'moonshot_batch',
                        'location_confidence': 'medium' if item.get('confidence', 0) > 0.7 else 'low'
                    }

            # Store results in batch state manager
            batch_state.store_batch_results(location_map)

            logger.info(f"[Moonshot] Location batch processed: {len(location_map)} results")
            return location_map
        
        # If we get here, processing failed
        raise Exception("No valid response or failed to parse JSON")

    except Exception as e:
        logger.error(f"[Moonshot] Batch location extraction failed: {e}")
        
        # Re-queue entries for retry (BatchStateManager handles retry logic)
        for batch_entry in batch_entries:
            batch_state.queue_entry(batch_entry.entry, batch_entry.source_tag, batch_entry.uuid)

        return {}

def _apply_moonshot_locations(alerts: List[Dict], location_map: Dict):
    """Apply batch results to alerts list"""
    applied_count = 0
    for alert in alerts:
        uuid = alert.get('uuid')
        # Only apply to alerts that were queued for batch processing
        if alert.get("_batch_queued") and uuid in location_map:
            loc_data = location_map[uuid]
            
            # Update alert with Moonshot data
            alert.update(loc_data)
            alert.pop("_batch_queued", None)  # Remove the marker
            
            # Try geocode if we have city/country
            if loc_data.get('city') and GEOCODE_ENABLED:
                lat, lon = get_city_coords(loc_data['city'], loc_data['country'])
                if lat and lon:
                    alert['latitude'] = lat
                    alert['longitude'] = lon
                    alert['location_sharing'] = True
            
            applied_count += 1
            logger.debug(f"[Moonshot] Applied location: {loc_data.get('city', 'None')}, {loc_data.get('country', 'None')}")
    
    logger.info(f"[Moonshot] Applied {applied_count} of {len(location_map)} batch results")

# ---------------- Build alert ------

async def _build_alert_from_entry(
    entry: Dict[str, Any],
    source_url: str,
    client: httpx.AsyncClient,
    source_tag: Optional[str] = None,
    batch_mode: bool = False
) -> Optional[Dict[str, Any]]:
    """
    REFACTORED: Use the new modular alert building system.
    
    This function now delegates to the clean, testable components in
    alert_builder_refactored.py instead of the original 250-line monolith.
    """
    try:
        return await build_alert_from_entry_v2(
            entry=entry,
            source_url=source_url,
            client=client,
            source_tag=source_tag,
            batch_mode=batch_mode
        )
    except Exception as e:
        logger.error(f"[REFACTORED] Alert building failed: {e}")
        return None

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

async def ingest_feeds(feed_specs: List[Dict[str, Any]], limit: int = BATCH_LIMIT) -> List[Dict[str, Any]]:
    if not feed_specs:
        logger.warning("No feed specs provided!")
        return []
    results_alerts: List[Dict[str, Any]] = []
    limits = httpx.Limits(max_connections=MAX_CONCURRENCY, max_keepalive_connections=MAX_CONCURRENCY)
    async with httpx.AsyncClient(follow_redirects=True, limits=limits) as client:
        async def _fetch_feed(spec):
            logger.info("Fetching feed: %s", spec["url"])
            await _bucket_for(spec["url"]).acquire()
            start = time.perf_counter()
            try:
                r = await client.get(spec["url"], timeout=DEFAULT_TIMEOUT)
                r.raise_for_status()
                txt = r.text
                logger.info("Fetched feed OK: %s", spec["url"])
                _record_health(spec["url"], ok=True, latency_ms=(time.perf_counter()-start)*1000.0)
                return txt, spec
            except Exception as e:
                logger.error("Feed fetch failed for %s: %r", spec["url"], e)
                _record_health(spec["url"], ok=False, latency_ms=(time.perf_counter()-start)*1000.0, error=str(e))
                return None, spec

        feed_results = await asyncio.gather(*[_fetch_feed(s) for s in feed_specs], return_exceptions=False)

        sem = asyncio.Semaphore(max(1, ARTICLE_CONCURRENCY))
        async def _process_entry(entry, source_url, source_tag):
            async with sem:
                return await _build_alert_from_entry(entry, source_url, client, source_tag, batch_mode=True)

        for txt, spec in feed_results:
            if not txt:
                continue
            entries, source_url = _extract_entries(txt, spec["url"])
            tag = spec.get("tag", "")
            tasks = [asyncio.create_task(_process_entry(e, source_url, tag)) for e in entries]
            for coro in asyncio.as_completed(tasks):
                res = await coro
                if res:
                    kind = spec.get("kind", "unknown")
                    res.setdefault("source_kind", kind)
                    res.setdefault("source_priority", KIND_PRIORITY.get(kind, 999))
                    if tag:
                        res.setdefault("source_tag", tag)
                    results_alerts.append(res)
                    if len(results_alerts) >= limit:
                        break
            if len(results_alerts) >= limit:
                break

    # Process any queued Moonshot batch requests using proper state management
    batch_state = get_batch_state_manager()
    
    # Get any pending batch results (eliminates function attribute anti-pattern)
    batch_results = batch_state.get_pending_results()
    
    # ANTI-PATTERN FIXED: No longer using function attributes for global state
    # Old problematic code:
    # if hasattr(_build_alert_from_entry, '_pending_batch_results'):
    #     batch_results.update(_build_alert_from_entry._pending_batch_results)
    #     delattr(_build_alert_from_entry, '_pending_batch_results')
    
    # Process any remaining queued entries with async batch processing
    with _LOCATION_BATCH_LOCK:
        if _LOCATION_BATCH_BUFFER:
            logger.info(f"[Moonshot] Processing final batch of {len(_LOCATION_BATCH_BUFFER)} queued entries...")
            try:
                final_batch_results = await _process_location_batch(client)
                batch_results.update(final_batch_results)
            except Exception as e:
                logger.error(f"[Moonshot] Async batch processing failed: {e}")
                # ASYNC-UNIFIED FIX: No sync fallback, use proper async retry logic
                # Mark pending alerts with fallback method rather than breaking async context
                logger.warning("[Moonshot] Using fallback location method for pending alerts")
                for alert in results_alerts:
                    if alert.get('location_method') == 'batch_pending':
                        alert['location_method'] = 'fallback'
                        alert['location_confidence'] = 'none'

    # Apply batch results back to alerts using the clean helper function
    if batch_results:
        _apply_moonshot_locations(results_alerts, batch_results)
        logger.info(f"[Moonshot] Applied {len(batch_results)} batch results to alerts")
    
    # Clean stale batch markers from alerts before final processing
    stale_cleaned = _clean_stale_batch_markers(results_alerts)
    if stale_cleaned > 0:
        logger.info(f"[Moonshot] Cleaned {stale_cleaned} stale batch markers from alerts")

    # Handle any remaining pending alerts (safety check)
    pending_count = 0
    for alert in results_alerts:
        if alert.get('location_method') == 'batch_pending':
            alert['location_method'] = 'fallback'
            alert['location_confidence'] = 'none'
            alert.pop('_batch_queued', None)
            pending_count += 1
    
    if pending_count > 0:
        logger.warning(f"[Moonshot] {pending_count} alerts had pending location method, switched to fallback")

    # Log buffer health metrics for monitoring
    health_metrics = _get_buffer_health_metrics()
    logger.info(f"[Moonshot] Buffer health: size={health_metrics['buffer_size']}/{health_metrics['buffer_max_size']}, "
                f"utilization={health_metrics['buffer_utilization_percent']:.1f}%, "
                f"max_age={health_metrics['max_item_age_seconds']:.1f}s, "
                f"failed_batches={health_metrics['permanently_failed_batches']}")

    logger.info("Total processed alerts: %d (with %d batch results applied)", len(results_alerts), len(batch_results))
    return _dedupe_batch(results_alerts)