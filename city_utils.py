"""
city_utils.py - City geocoding and normalization utilities

This module provides city name normalization, geocoding, and location utilities
for the RSS processor location extraction pipeline.
"""

import os
import json
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger("city_utils")

# City/country mappings loaded from location_keywords.json
_CITY_COORDS_CACHE: Dict[str, Tuple[float, float]] = {}
_COUNTRY_COORDS_CACHE: Dict[str, Tuple[float, float]] = {}
_CITY_TO_COUNTRY_MAP: Dict[str, str] = {}

def _load_location_data():
    """Load city and country coordinate data from location_keywords.json"""
    global _CITY_COORDS_CACHE, _COUNTRY_COORDS_CACHE, _CITY_TO_COUNTRY_MAP
    
    try:
        location_file = os.path.join(os.path.dirname(__file__), "location_keywords.json")
        if os.path.exists(location_file):
            with open(location_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Extract cities and countries
            cities = data.get('cities', [])
            countries = data.get('countries', [])
            
            logger.info(f"Loaded {len(cities)} cities and {len(countries)} countries from location_keywords.json")
            
            # Build simple coordinate approximations (for demo purposes)
            # In production, you'd use a proper geocoding service or database
            for city in cities:
                city_lower = city.lower()
                # Simple hash-based coordinate assignment for demo
                lat = 40.0 + (hash(city_lower) % 100) * 0.5
                lon = -100.0 + (hash(city_lower) % 200) * 0.5 
                _CITY_COORDS_CACHE[city_lower] = (lat, lon)
                
            for country in countries:
                country_lower = country.lower()
                # Simple hash-based coordinate assignment for demo  
                lat = 30.0 + (hash(country_lower) % 120) * 0.5
                lon = -150.0 + (hash(country_lower) % 300) * 0.5
                _COUNTRY_COORDS_CACHE[country_lower] = (lat, lon)
                
    except Exception as e:
        logger.warning(f"Could not load location data: {e}")

# Load data on module import
_load_location_data()

def get_city_coords(city: str, country: Optional[str] = None) -> Tuple[Optional[float], Optional[float]]:
    """
    Get coordinates for a city, optionally filtered by country.
    
    Args:
        city: City name
        country: Optional country name for disambiguation
        
    Returns:
        Tuple of (latitude, longitude) or (None, None) if not found
    """
    if not city:
        return None, None
        
    city_key = city.lower().strip()
    
    # First try database lookup if available
    try:
        from db_utils import fetch_one
        if fetch_one:
            cache_ttl_days = int(os.getenv("GEOCODE_CACHE_TTL_DAYS", "180"))
            row = fetch_one(
                """
                SELECT lat, lon
                FROM geocode_cache
                WHERE city = %s
                  AND COALESCE(country,'') = COALESCE(%s,'')
                  AND updated_at > NOW() - (%s || ' days')::interval
                """,
                (city, country, str(cache_ttl_days)),
            )
            if row:
                lat, lon = row
                return float(lat), float(lon)
    except Exception as e:
        logger.debug(f"Database geocode lookup failed: {e}")
    
    # Fallback to in-memory cache
    coords = _CITY_COORDS_CACHE.get(city_key)
    if coords:
        return coords
        
    logger.debug(f"No coordinates found for city: {city}")
    return None, None

def fuzzy_match_city(text: str) -> Optional[str]:
    """
    Attempt to find a city name in the given text using fuzzy matching.
    
    Args:
        text: Text to search for city names
        
    Returns:
        Matched city name or None
    """
    if not text:
        return None
        
    text_lower = text.lower()
    
    # Simple substring matching against known cities
    for city in _CITY_COORDS_CACHE.keys():
        if city in text_lower and len(city) > 3:  # Avoid short matches
            return city.title()
            
    return None

def normalize_city_country(city: str, country: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalize city and country names to standard format.
    
    Args:
        city: Raw city name
        country: Raw country name
        
    Returns:
        Tuple of (normalized_city, normalized_country)
    """
    normalized_city = None
    normalized_country = None
    
    if city:
        city_clean = city.strip().title()
        # Check if it's a known city
        if city.lower() in _CITY_COORDS_CACHE:
            normalized_city = city_clean
            
    if country:
        country_clean = country.strip().title()
        # Check if it's a known country
        if country.lower() in _COUNTRY_COORDS_CACHE:
            normalized_country = country_clean
            
    return normalized_city, normalized_country

def get_country_for_city(city: str) -> Optional[str]:
    """
    Get the country for a given city name.
    
    Args:
        city: City name
        
    Returns:
        Country name or None
    """
    if not city:
        return None
        
    # This would ideally come from a proper database
    # For now, return None since we don't have city->country mappings
    return _CITY_TO_COUNTRY_MAP.get(city.lower())

def cache_geocode_result(city: str, country: Optional[str], lat: float, lon: float):
    """
    Cache a geocoding result in the database.
    
    Args:
        city: City name
        country: Country name
        lat: Latitude
        lon: Longitude
    """
    try:
        from db_utils import execute
        if execute:
            execute(
                """
                INSERT INTO geocode_cache (city, country, lat, lon, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (city, COALESCE(country, ''))
                DO UPDATE SET lat = EXCLUDED.lat, lon = EXCLUDED.lon, updated_at = NOW()
                """,
                (city, country, lat, lon)
            )
            logger.debug(f"Cached geocode result: {city}, {country} -> {lat}, {lon}")
    except Exception as e:
        logger.debug(f"Failed to cache geocode result: {e}")

# Health check function
def get_city_utils_stats() -> Dict[str, Any]:
    """Get statistics about loaded city data"""
    return {
        "cities_loaded": len(_CITY_COORDS_CACHE),
        "countries_loaded": len(_COUNTRY_COORDS_CACHE),
        "city_country_mappings": len(_CITY_TO_COUNTRY_MAP)
    }
