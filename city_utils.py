# city_utils.py — lightweight city inference + optional geocoding • v2025-08-24 DEBUGGED+LOGGING
from __future__ import annotations

import os
import re
import difflib
import logging
from typing import Optional, Tuple, Iterable

logger = logging.getLogger("city_utils")
logging.basicConfig(level=logging.DEBUG, force=True)
logger.critical("[city_utils] LOADED: city_utils.py imported and logger initialized.")
logger.info(f"[city_utils] ENV: CITYUTILS_ENABLE_GEOCODE={os.getenv('CITYUTILS_ENABLE_GEOCODE')!r}, "
            f"GEOCODE_ENABLED={str(os.getenv('CITYUTILS_ENABLE_GEOCODE', 'true')).lower() in ('1','true','yes','y')}")

# ---------------- Env switches (no-network by default if you want) ----------------
GEOCODE_ENABLED = str(os.getenv("CITYUTILS_ENABLE_GEOCODE", "true")).lower() in ("1", "true", "yes", "y")
GEOCODE_TIMEOUT_SEC = float(os.getenv("CITYUTILS_GEOCODE_TIMEOUT_SEC", "3"))
GEOCODE_MIN_DELAY   = float(os.getenv("CITYUTILS_GEOCODE_MIN_DELAY_SEC", "1"))
GEOCODE_MAX_RETRIES = int(os.getenv("CITYUTILS_GEOCODE_MAX_RETRIES", "0"))
GEOCODE_ERROR_WAIT  = float(os.getenv("CITYUTILS_GEOCODE_ERROR_WAIT_SEC", "0"))

try:
    from unidecode import unidecode
except Exception:
    def unidecode(s: str) -> str:
        return s

def _norm(s: str) -> str:
    return unidecode(s or "").strip().lower()

def _titlecase(s: str) -> str:
    return " ".join([p.capitalize() for p in (s or "").split()])

# ---------------- Optional geocoder (strictly sandboxed) ----------------
_geocode = None
_geocode_debug_msg = None
if GEOCODE_ENABLED:
    try:
        from geopy.geocoders import Nominatim
        from geopy.extra.rate_limiter import RateLimiter
        # ✅ FIX: removed deprecated scheme="https"
        _geolocator = Nominatim(user_agent="sentinel-geocoder", timeout=GEOCODE_TIMEOUT_SEC)
        _geocode = RateLimiter(
            _geolocator.geocode,
            min_delay_seconds=GEOCODE_MIN_DELAY,
            swallow_exceptions=True,
            max_retries=GEOCODE_MAX_RETRIES,
            error_wait_seconds=GEOCODE_ERROR_WAIT,
        )
        logger.info("[city_utils] Geopy geocoder loaded and enabled.")
    except Exception as e:
        _geocode_debug_msg = f"Failed to init geopy: {e}"
        logger.error("[city_utils] ERROR loading geopy: %s", e)
        _geocode = None
else:
    logger.info("[city_utils] Geocoding globally DISABLED via env.")

_COMMON_CITIES: Iterable[str] = [
    "New York","London","Paris","Berlin","Moscow","Kyiv","Warsaw","Prague","Budapest","Bucharest",
    "Rome","Madrid","Barcelona","Lisbon","Dublin","Edinburgh","Istanbul","Ankara","Athens","Sofia",
    "Stockholm","Oslo","Copenhagen","Helsinki","Reykjavik",
    "Cairo","Lagos","Nairobi","Johannesburg","Cape Town","Casablanca","Tunis","Algiers","Addis Ababa","Accra",
    "Tel Aviv","Jerusalem","Riyadh","Jeddah","Dubai","Abu Dhabi","Doha","Kuwait City","Manama","Muscat",
    "Tehran","Baghdad","Beirut","Amman","Damascus",
    "Mumbai","Delhi","Bengaluru","Chennai","Hyderabad","Kolkata","Karachi","Lahore","Dhaka","Kathmandu","Colombo",
    "Beijing","Shanghai","Shenzhen","Guangzhou","Hong Kong","Macau","Taipei","Seoul","Tokyo","Osaka",
    "Bangkok","Jakarta","Manila","Kuala Lumpur","Singapore","Hanoi","Ho Chi Minh City",
    "Sydney","Melbourne","Auckland","Wellington",
    "Mexico City","Bogotá","Lima","Santiago","Buenos Aires","São Paulo","Rio de Janeiro","Montevideo",
    "Toronto","Vancouver","Montreal","Chicago","Los Angeles","San Francisco","Washington","Boston","Miami","Houston",
]

def fuzzy_match_city(text: str, *, min_ratio: float = 0.84) -> Optional[str]:
    logger.debug(f"[city_utils] fuzzy_match_city called: text={text!r}, min_ratio={min_ratio}")
    text = _norm(text)
    if not text:
        logger.debug("[city_utils] fuzzy_match_city: No text after normalization.")
        return None
    best = None
    best_ratio = min_ratio
    for city in _COMMON_CITIES:
        ratio = difflib.SequenceMatcher(None, text, city.lower()).ratio()
        if ratio > best_ratio:
            best = city
            best_ratio = ratio
    logger.debug(f"[city_utils] fuzzy_match_city: best match for {text!r} is {best!r} (ratio={best_ratio})")
    return best

def normalize_city(city_like: str) -> Tuple[Optional[str], Optional[str]]:
    logger.critical(f"[city_utils] normalize_city CALLED with city_like={city_like!r}")
    if not city_like:
        logger.warning("[city_utils] normalize_city called with empty input.")
        return None, None

    raw = _norm(city_like)
    city_hint, country_hint = None, None
    if "," in raw:
        parts = [p.strip() for p in raw.split(",", 1)]
        city_hint = parts[0] or None
        country_hint = parts[1] or None

    if GEOCODE_ENABLED and _geocode:
        q = f"{city_hint or raw}{', ' + country_hint if country_hint else ''}"
        try:
            logger.info(f"[city_utils] Attempting geocode for '{q}'")
            loc = _geocode(q)
            if loc and getattr(loc, "raw", None):
                addr = loc.raw.get("address", {})
                city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or addr.get("state")
                country = addr.get("country")
                logger.info(f"[city_utils] Geocoded '{q}' → city='{city}', country='{country}'")
                if city or country:
                    return (_titlecase(city) if city else (_titlecase(city_hint) if city_hint else None),
                            _titlecase(country) if country else (_titlecase(country_hint) if country_hint else None))
                else:
                    logger.warning(f"[city_utils] Geocoding returned no city/country for '{q}'")
            else:
                logger.warning(f"[city_utils] Geocoding returned None for '{q}'")
        except Exception as e:
            logger.error(f"[city_utils] Geocode exception for '{q}': {e}")
            pass
    else:
        logger.warning(f"[city_utils] Geocoding not enabled or unavailable for '{city_like}' (city_hint={city_hint}, country_hint={country_hint})")

    logger.warning(f"[city_utils] Geocode fallback for '{city_like}' (city_hint={city_hint}, country_hint={country_hint})")
    return _titlecase(city_hint or raw), (_titlecase(country_hint) if country_hint else None)

def get_city_coords(city: Optional[str], country: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    logger.critical(f"[city_utils] get_city_coords CALLED with city={city!r}, country={country!r}")
    if not city:
        logger.warning("[city_utils] get_city_coords called with empty city.")
        return None, None

    if not GEOCODE_ENABLED:
        logger.info("[city_utils] Geocoding disabled via env; skipping geocode for '%s', '%s'.", city, country)
        return None, None

    if not _geocode:
        logger.error("[city_utils] Geocoding unavailable (geopy missing or init failed: %s); skipping for '%s', '%s'.", _geocode_debug_msg, city, country)
        return None, None

    q = f"{city}{', ' + country if country else ''}"
    try:
        logger.info(f"[city_utils] Attempting geocode for '{q}'")
        loc = _geocode(q)
        if loc:
            logger.info(f"[city_utils] Geocoded '{q}' → ({loc.latitude}, {loc.longitude})")
            return float(loc.latitude), float(loc.longitude)
        else:
            logger.warning(f"[city_utils] FAILED to geocode: '{q}'")
    except Exception as e:
        logger.error(f"[city_utils] ERROR geocoding '{q}': {e}")
    return None, None

def normalize_city_country(city: Optional[str], country: Optional[str]) -> Tuple[str, str]:
    logger.critical(f"[city_utils] normalize_city_country CALLED with city={city!r}, country={country!r}")
    c = _norm(city or "")
    k = _norm(country or "")
    return c, k
