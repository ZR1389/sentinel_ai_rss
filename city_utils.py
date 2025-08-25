# city_utils.py — Python 3.13-safe city utilities (no geopy, no backoff) • v2025-08-24
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Iterable, Optional, Tuple

# ------------------------------------------------------------------------------
# Logging (library-friendly: don’t hijack global config)
# ------------------------------------------------------------------------------
logger = logging.getLogger("city_utils")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ------------------------------------------------------------------------------
# Env / Config
# ------------------------------------------------------------------------------
GEOCODE_ENABLED: bool = str(os.getenv("CITYUTILS_ENABLE_GEOCODE", "true")).lower() in ("1", "true", "yes", "y")
NOMINATIM_URL: str = os.getenv("CITYUTILS_NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
USER_AGENT: str = os.getenv("CITYUTILS_USER_AGENT", "sentinel-city-utils/1.0 (+https://zikarisk.com)")
CONTACT_EMAIL: str = os.getenv("CITYUTILS_CONTACT_EMAIL", "").strip()  # optional but recommended for Nominatim
HTTP_TIMEOUT: float = float(os.getenv("CITYUTILS_HTTP_TIMEOUT_SEC", "12"))
HTTP_RETRIES: int = int(os.getenv("CITYUTILS_HTTP_RETRIES", "0"))  # ← no backoff; 0 means single attempt

# ------------------------------------------------------------------------------
# Normalization helpers
# ------------------------------------------------------------------------------
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s\-]")

def _norm_lower(s: str) -> str:
    """Aggressive, lowercase normalization for matching/cache keys."""
    s = (s or "").strip()
    s = _WHITESPACE_RE.sub(" ", s)
    s = _PUNCT_RE.sub("", s)
    return s.lower()

def _titlecase(s: str) -> str:
    return " ".join(p.capitalize() for p in (s or "").split())

def normalize_city(name: str) -> str:
    """Pretty, Title-Cased city string for storage/UI."""
    return _titlecase(_norm_lower(name))

def normalize_city_country(city: Optional[str], country: Optional[str]) -> Tuple[str, str]:
    """
    Pretty, Title-Cased (city, country) pair for storage/UI.
    (Keeps your DB consistent without forcing specific ISO names.)
    """
    return _titlecase(_norm_lower(city or "")), _titlecase(_norm_lower(country or ""))

# ------------------------------------------------------------------------------
# Lightweight fuzzy city detection
# ------------------------------------------------------------------------------
_COMMON_CITIES: Tuple[str, ...] = (
    "New York","London","Paris","Berlin","Madrid","Rome","Tokyo","Seoul","Beijing","Shanghai",
    "Hong Kong","Singapore","Sydney","Melbourne","Auckland","Cairo","Istanbul","Dubai","Mumbai","Delhi",
    "Bengaluru","Karachi","Johannesburg","Nairobi","Lagos","Kinshasa","Mexico City","Bogotá","Lima",
    "Santiago","Buenos Aires","São Paulo","Rio de Janeiro","Montevideo","Toronto","Vancouver","Montreal",
    "Chicago","Los Angeles","San Francisco","Washington","Boston","Miami","Houston"
)

def fuzzy_match_city(text: str, *, min_ratio: float = 0.84) -> Optional[str]:
    try:
        import difflib
        t = _norm_lower(text)
        if not t:
            return None
        best = None
        best_ratio = min_ratio
        for city in _COMMON_CITIES:
            ratio = difflib.SequenceMatcher(None, t, city.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = city
        logger.debug("[city_utils] fuzzy_match_city(%r) -> %r (ratio=%.3f)", text, best, best_ratio)
        return best
    except Exception as e:
        logger.error("[city_utils] fuzzy_match_city error: %s", e)
        return None

# ------------------------------------------------------------------------------
# Geocoding (Nominatim via stdlib urllib; NO BACKOFF/SLEEPS)
# ------------------------------------------------------------------------------
def _http_get_json(url: str, params: dict, *, timeout: float = HTTP_TIMEOUT, retries: int = HTTP_RETRIES):
    """
    GET JSON with optional instantaneous retries (no sleeps, no backoff).
    """
    qs = urllib.parse.urlencode(params)
    full_url = f"{url}?{qs}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_err = None
    for _ in range(max(0, retries) + 1):
        req = urllib.request.Request(full_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8")
                if status == 200:
                    return json.loads(body)
                logger.warning("[city_utils] Nominatim non-200 status=%s body[:200]=%r", status, body[:200])
                last_err = f"status={status}"
        except Exception as e:
            last_err = e
            logger.debug("[city_utils] HTTP error on %s: %s", full_url, e)
            continue
    if last_err:
        logger.warning("[city_utils] Nominatim request failed: %s", last_err)
    return None

@lru_cache(maxsize=4096)
def _geocode_city_cached(query: str) -> Tuple[Optional[float], Optional[float]]:
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "addressdetails": 0,
    }
    if CONTACT_EMAIL:
        params["email"] = CONTACT_EMAIL  # recommended by Nominatim usage policy
    data = _http_get_json(NOMINATIM_URL, params)
    if not data:
        return None, None
    try:
        first = data[0]
        return float(first["lat"]), float(first["lon"])
    except Exception as e:
        logger.error("[city_utils] Failed to parse geocode response for %r: %s", query, e)
        return None, None

def get_city_coords(city_name: Optional[str], country: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Get (lat, lon) for a city using OpenStreetMap Nominatim.
    Returns (None, None) on failure. Honors CITYUTILS_ENABLE_GEOCODE toggle.
    No sleeps/backoff are performed (instant retries only if HTTP_RETRIES>0).
    """
    if not GEOCODE_ENABLED:
        logger.info("[city_utils] Geocoding disabled via CITYUTILS_ENABLE_GEOCODE.")
        return None, None

    c = _norm_lower(city_name or "")
    k = _norm_lower(country or "")
    if not c:
        logger.warning("[city_utils] get_city_coords called with empty city_name.")
        return None, None

    query = f"{c}, {k}" if k else c
    lat, lon = _geocode_city_cached(query)
    if lat is not None and lon is not None:
        logger.info("[city_utils] Geocoded %r -> (%s, %s)", query, lat, lon)
    else:
        logger.warning("[city_utils] No geocoding data for %r", query)
    return lat, lon

# ------------------------------------------------------------------------------
# Bulk helper
# ------------------------------------------------------------------------------
def batch_get_coords(pairs: Iterable[Tuple[str, str]]) -> Iterable[Tuple[str, str, Optional[float], Optional[float]]]:
    for city, country in pairs:
        lat, lon = get_city_coords(city, country)
        yield normalize_city(city), _titlecase(_norm_lower(country or "")), lat, lon

__all__ = [
    "normalize_city",
    "normalize_city_country",
    "fuzzy_match_city",
    "get_city_coords",
    "batch_get_coords",
]
