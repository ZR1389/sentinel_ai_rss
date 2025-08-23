# city_utils.py — lightweight city inference + optional geocoding • v2025-08-22
from __future__ import annotations
import re
import difflib
from typing import Optional, Tuple, Iterable

try:
    from unidecode import unidecode
except Exception:
    def unidecode(s: str) -> str:  # no-op fallback
        return s

# ----- Optional geocoder (safe fallback if missing) -----
try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
    _geolocator = Nominatim(user_agent="sentinel-geocoder")
    _geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)
except Exception:
    _geolocator = None
    _geocode = None

# A small, fast global list (avoid importing heavy modules in hot path)
# Add more cities you care about; order roughly by prominence.
_COMMON_CITIES = [
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

# ---------------------- Normalization helpers ----------------------
def _norm(s: str) -> str:
    if not s:
        return ""
    s = unidecode(s)
    s = s.replace("–", " ").replace("—", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _titlecase(s: str) -> str:
    return " ".join(p.capitalize() for p in (s or "").split())

# ---------------------- Public API (expected by callers) ----------------------
def fuzzy_match_city(text: str, *, min_ratio: float = 0.84) -> Optional[str]:
    """
    Best-effort city guess from free text. NO geocoding here.
    Returns a city string (optionally like 'City, Country' if we detect both), else None.
    """
    if not text:
        return None
    t = _norm(text)

    # 1) Try patterns like "in Paris, France", "near Lagos, Nigeria", "at Berlin"
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

    # 2) Scan for well-known city names (cheap dictionary match)
    low = t.lower()
    for c in _COMMON_CITIES:
        cn = _norm(c).lower()
        # word-boundary-ish check
        if re.search(rf'\b{re.escape(cn)}\b', low):
            return _titlecase(c)

    # 3) Fuzzy fallback against the common list
    tokens = set(re.findall(r"[A-Za-z][A-Za-z\-']{2,}(?:\s+[A-Za-z][A-Za-z\-']{2,}){0,2}", text))
    candidates = [_titlecase(_norm(tok)) for tok in tokens]
    if candidates:
        best = difflib.get_close_matches(
            " ".join(sorted(candidates, key=len, reverse=True))[:60],  # rough seed
            _COMMON_CITIES, n=1, cutoff=min_ratio
        )
        if best:
            return best[0]
    return None

def normalize_city(city_like: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Input: 'Paris' or 'Paris, France' (any casing/punctuation).
    Output: (CityName, CountryName) — both title-cased if known, else (fallback_city, None).
    Uses geocoding if available; never raises.
    """
    if not city_like:
        return None, None
    raw = _norm(city_like)
    # If user passed "City, Country", split to assist geocoder
    city_hint, country_hint = None, None
    if "," in raw:
        parts = [p.strip() for p in raw.split(",", 1)]
        if parts:
            city_hint = parts[0] or None
            country_hint = parts[1] or None

    # Try geocoding (with hints if present)
    if _geocode:
        q = f"{city_hint or raw}{', ' + country_hint if country_hint else ''}"
        try:
            loc = _geocode(q)
            if loc and getattr(loc, "raw", None):
                addr = loc.raw.get("address", {})
                city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or addr.get("state")
                country = addr.get("country")
                if city or country:
                    return (_titlecase(city) if city else None,
                            _titlecase(country) if country else None)
        except Exception:
            pass

    # Fallback: just normalize casing; country unknown
    return _titlecase(city_hint or raw), (_titlecase(country_hint) if country_hint else None)

def get_city_coords(city: Optional[str], country: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Given a city and optional country, return (lat, lon) floats via Nominatim.
    Returns (None, None) if unavailable or not found. Never raises.
    """
    if not city:
        return None, None
    if _geocode is None:
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
