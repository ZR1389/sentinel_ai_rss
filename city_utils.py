# city_utils.py — lightweight city inference + optional geocoding • v2025-08-23
from __future__ import annotations

import os
import re
import difflib
from typing import Optional, Tuple, Iterable

# ---------------- Env switches (no-network by default if you want) ----------------
GEOCODE_ENABLED = str(os.getenv("CITYUTILS_ENABLE_GEOCODE", "true")).lower() in ("1", "true", "yes", "y")
GEOCODE_TIMEOUT_SEC = float(os.getenv("CITYUTILS_GEOCODE_TIMEOUT_SEC", "3"))       # keep very short
GEOCODE_MIN_DELAY   = float(os.getenv("CITYUTILS_GEOCODE_MIN_DELAY_SEC", "1"))     # Nominatim policy ~1s
GEOCODE_MAX_RETRIES = int(os.getenv("CITYUTILS_GEOCODE_MAX_RETRIES", "0"))         # zero = no retry
GEOCODE_ERROR_WAIT  = float(os.getenv("CITYUTILS_GEOCODE_ERROR_WAIT_SEC", "0"))    # no extra waits

# ---------------- Normalization helpers ----------------
try:
    from unidecode import unidecode
except Exception:
    def unidecode(s: str) -> str:  # no-op fallback
        return s

def _norm(s: str) -> str:
    if not s:
        return ""
    s = unidecode(s)
    s = s.replace("–", " ").replace("—", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _titlecase(s: str) -> str:
    return " ".join(p.capitalize() for p in (s or "").split())

# ---------------- Optional geocoder (strictly sandboxed) ----------------
_geocode = None
if GEOCODE_ENABLED:
    try:
        from geopy.geocoders import Nominatim
        from geopy.extra.rate_limiter import RateLimiter
        # NOTE: timeout kept short; no retries; swallow exceptions so we never bubble/block
        _geolocator = Nominatim(user_agent="sentinel-geocoder", timeout=GEOCODE_TIMEOUT_SEC, scheme="https")
        _geocode = RateLimiter(
            _geolocator.geocode,
            min_delay_seconds=GEOCODE_MIN_DELAY,
            swallow_exceptions=True,
            max_retries=GEOCODE_MAX_RETRIES,
            error_wait_seconds=GEOCODE_ERROR_WAIT,
        )
    except Exception:
        _geocode = None

# ---------------- A small, fast global list for cheap matches ----------------
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

# ---------------- Public API (expected by callers) ----------------
def fuzzy_match_city(text: str, *, min_ratio: float = 0.84) -> Optional[str]:
    """
    Best-effort city guess from free text. NO geocoding here.
    Returns a city string (optionally 'City, Country' if detected), else None.
    """
    if not text:
        return None
    t = _norm(text)

    # 1) "in Paris, France" / "near Lagos, Nigeria" / "at Berlin"
    pat_pairs = re.compile(
        r'\b(?:in|near|at|outside|around|north of|south of|east of|west of|city of)\s+'
        r'([A-Z][A-Za-z\'’.\-]+(?:\s+[A-Z][A-Za-z\'’.\-]+){0,2})'
        r'(?:\s*,\s*([A-Z][A-Za-z\'’.\-]+))?'
    )
    for m in pat_pairs.finditer(text):
        city = _titlecase(_norm(m.group(1)))
        country = _titlecase(_norm(m.group(2))) if m.group(2) else None
        if city:
            return f"{city}, {country}" if country else city

    # 2) Cheap dictionary match
    low = t.lower()
    for c in _COMMON_CITIES:
        cn = _norm(c).lower()
        if re.search(rf'\b{re.escape(cn)}\b', low):
            return _titlecase(c)

    # 3) Fuzzy fallback against common list (bounded tokens)
    tokens = set(re.findall(r"[A-Za-z][A-Za-z\-']{2,}(?:\s+[A-Za-z][A-Za-z\-']{2,}){0,2}", text))
    if tokens:
        candidates = [_titlecase(_norm(tok)) for tok in list(tokens)[:40]]  # cap to avoid CPU spikes
        seed = " ".join(sorted(candidates, key=len, reverse=True))[:60]
        best = difflib.get_close_matches(seed, list(_COMMON_CITIES), n=1, cutoff=min_ratio)
        if best:
            return best[0]
    return None

def normalize_city(city_like: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Input: 'Paris' or 'Paris, France' (any casing/punctuation).
    Output: (CityName, CountryName) — title-cased if known. Uses geocoding only if enabled.
    Never raises; returns best-effort normalization even without network.
    """
    if not city_like:
        return None, None

    raw = _norm(city_like)
    city_hint, country_hint = None, None
    if "," in raw:
        parts = [p.strip() for p in raw.split(",", 1)]
        city_hint = parts[0] or None
        country_hint = parts[1] or None

    # Geocode (fast-exit: disabled or unavailable)
    if GEOCODE_ENABLED and _geocode:
        q = f"{city_hint or raw}{', ' + country_hint if country_hint else ''}"
        try:
            loc = _geocode(q)
            if loc and getattr(loc, "raw", None):
                addr = loc.raw.get("address", {})
                city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or addr.get("state")
                country = addr.get("country")
                if city or country:
                    return (_titlecase(city) if city else (_titlecase(city_hint) if city_hint else None),
                            _titlecase(country) if country else (_titlecase(country_hint) if country_hint else None))
        except Exception:
            # swallow per design; fall through to heuristic normalization
            pass

    # Fallback: heuristic-only normalization; country may remain None
    return _titlecase(city_hint or raw), (_titlecase(country_hint) if country_hint else None)

def get_city_coords(city: Optional[str], country: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Given a city and optional country, return (lat, lon) via Nominatim.
    Respects env switch; returns (None, None) on any issue. Never raises or retries.
    """
    if not city or not (GEOCODE_ENABLED and _geocode):
        return None, None
    try:
        q = f"{city}{', ' + country if country else ''}"
        loc = _geocode(q)
        if loc:
            return float(loc.latitude), float(loc.longitude)
    except Exception:
        pass
    return None, None

def normalize_city_country(city: Optional[str], country: Optional[str]) -> Tuple[str, str]:
    """
    Legacy helper: returns lowercased/diacritic-stripped strings (not geocoded).
    """
    c = _norm(city or "")
    k = _norm(country or "")
    return c, k
