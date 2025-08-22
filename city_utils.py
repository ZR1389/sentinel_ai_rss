import difflib
import unidecode
import re

# For dynamic geocoding:
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

# Initialize Nominatim geocoder (OpenStreetMap, free for moderate use)
_geolocator = Nominatim(user_agent="sentinel-geocoder")
_geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)

def normalize_city(city_name):
    """
    Normalize city names:
      - Lowercase
      - Remove leading/trailing whitespace
      - Remove punctuation
      - Remove accents/diacritics
    """
    if not city_name:
        return ""
    city = unidecode.unidecode(city_name)
    city = city.lower()
    city = re.sub(r'[^\w\s]', '', city)
    city = city.strip()
    return city

def normalize_country(country_name):
    """
    Normalize and alias country names for geocoding.
    """
    if not country_name:
        return ""
    country = unidecode.unidecode(country_name)
    country = country.lower().strip()
    country = re.sub(r'[^\w\s]', '', country)
    return country

def fuzzy_match_city(city_name, candidates, min_ratio=0.8):
    """
    Fuzzy match a city name to a list of candidate city names.
    Returns the best matching candidate or None if no match above min_ratio.
    """
    if not city_name or not candidates:
        return None

    norm_target = normalize_city(city_name)
    norm_candidates = [normalize_city(c) for c in candidates]

    for idx, norm_c in enumerate(norm_candidates):
        if norm_target == norm_c:
            return candidates[idx]

    matches = difflib.get_close_matches(norm_target, norm_candidates, n=1, cutoff=min_ratio)
    if matches:
        idx = norm_candidates.index(matches[0])
        return candidates[idx]
    return None

def get_city_coords(city, country):
    """
    Given a city and country, return (latitude, longitude) as floats using Nominatim geocoding.
    Returns (None, None) if not found.
    """
    if not city or not country:
        return None, None
    try:
        location = _geocode(f"{city}, {country}")
        if location:
            return location.latitude, location.longitude
    except Exception:
        pass
    return None, None

def normalize_city_country(city, country):
    """
    Normalize both city and country for display or matching.
    """
    return normalize_city(city), normalize_country(country)