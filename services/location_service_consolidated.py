"""
Consolidated location extraction service with deterministic methods.
Enhanced with expanded location_keywords.json integration and robust error handling.
Used as first pass before Moonshot batch processing for ambiguous cases.
"""
import re
import logging
import json
import os
from typing import Optional, Tuple, NamedTuple, Dict, Any

try:
    from unidecode import unidecode
except ImportError as e:
    logging.getLogger(__name__).warning(f"[UNIDECODE] unidecode library not available, text normalization will be degraded: {e}")
    def unidecode(s: str) -> str:  # type: ignore
        return s

logger = logging.getLogger(__name__)

class LocationResult(NamedTuple):
    city: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    location_method: Optional[str] = None
    location_confidence: Optional[str] = None

# Global variables for loaded location data
_LOCATION_KEYWORDS: Optional[Dict[str, Any]] = None
_LOCATION_KEYWORDS_LOADED = False

def _load_location_keywords() -> Dict[str, Any]:
    """Load location keywords with robust error handling"""
    global _LOCATION_KEYWORDS, _LOCATION_KEYWORDS_LOADED
    
    if _LOCATION_KEYWORDS_LOADED:
        return _LOCATION_KEYWORDS or {}
    
    _LOCATION_KEYWORDS_LOADED = True
    
    # Try multiple possible paths
    possible_paths = [
        "config/location_keywords.json",
        "location_keywords.json",
        os.path.join(os.path.dirname(__file__), "config", "location_keywords.json"),
        os.path.join(os.path.dirname(__file__), "location_keywords.json")
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Validate structure
                if not isinstance(data, dict):
                    logger.warning(f"[LocationService] Invalid structure in {path}: not a dictionary")
                    continue
                    
                if 'countries' not in data or 'cities' not in data:
                    logger.warning(f"[LocationService] Missing required sections in {path}")
                    continue
                
                _LOCATION_KEYWORDS = data
                logger.info(f"[LocationService] Loaded {len(data.get('countries', {}))} countries, {len(data.get('cities', {}))} cities from {path}")
                return _LOCATION_KEYWORDS
                
            except json.JSONDecodeError as e:
                logger.error(f"[LocationService] Invalid JSON in {path}: {e}")
                continue
            except Exception as e:
                logger.error(f"[LocationService] Failed to load {path}: {e}")
                continue
    
    # Fallback empty structure
    logger.warning(f"[LocationService] Could not load location keywords from any path: {possible_paths}")
    _LOCATION_KEYWORDS = {"countries": {}, "cities": {}, "regions": {}}
    return _LOCATION_KEYWORDS

def _get_location_data() -> Dict[str, Any]:
    """Get location data with error handling"""
    try:
        return _load_location_keywords()
    except Exception as e:
        logger.error(f"[LocationService] Error accessing location data: {e}")
        return {"countries": {}, "cities": {}, "regions": {}}

# Enhanced patterns for deterministic location extraction
CITY_COUNTRY_PATTERNS = [
    # "Event in City, Country" - most common news format
    r'\b(?:in|at|near|from)\s+([A-Z][a-zA-Z\s\-\'\.]+),\s*([A-Z][a-zA-Z\s\-\'\.]+?)(?:\s|$|[,.!])',
    # "City, Country - description" - news headline format
    r'^([A-Z][a-zA-Z\s\-\'\.]+),\s*([A-Z][a-zA-Z\s\-\'\.]+?)\s*[-–—]\s*',
    # (City, Country) format
    r'\(([A-Z][a-zA-Z\s\-\'\.]+),\s*([A-Z][a-zA-Z\s\-\'\.]+?)\)',
    # "CITY, COUNTRY:" format
    r'^([A-Z][A-Za-z\s\-\'\.]+),\s*([A-Z][A-Za-z\s\-\'\.]+?)\s*:\s*',
    # Enhanced dateline format: "CITY, Country (Reuters)" etc.
    r'\b([A-Z][A-Za-z\s\-\'\.]+),\s*([A-Z][A-Za-z\s\-\'\.]+?)\s*\([^)]*\)',
]

CITY_ONLY_PATTERNS = [
    # "CITY: description" or "CITY -" (all caps city names)
    r'^([A-Z]{3,})\s*[:–—-]\s*',
    # "CITY (" format for datelines
    r'^([A-Z]{3,})\s*\(\s*',
]

COUNTRY_PATTERNS = [
    # Country-specific phrases (known entities only) - enhanced list
    r'\b(United States|United Kingdom|South Korea|North Korea|Saudi Arabia|South Africa|New Zealand|United Arab Emirates|Czech Republic|Dominican Republic|Costa Rica|Puerto Rico|Sri Lanka|Bosnia and Herzegovina|Democratic Republic of Congo|Central African Republic)\b',
    r'\b(USA|UK|US|UAE|EU|DRC|CAR)\b',
    # European countries that often appear in news
    r'\b(France|Germany|Italy|Spain|Netherlands|Belgium|Switzerland|Austria|Poland|Sweden|Norway|Denmark|Finland)\b',
    # Major Asian countries
    r'\b(China|Japan|India|Indonesia|Thailand|Vietnam|Malaysia|Singapore|Philippines|Pakistan|Bangladesh)\b',
    # African countries frequently in news
    r'\b(Nigeria|Egypt|Ethiopia|Kenya|Ghana|Morocco|Algeria|Tunisia|Libya|Sudan)\b',
    # Middle Eastern countries
    r'\b(Israel|Palestine|Jordan|Lebanon|Syria|Iraq|Iran|Turkey|Yemen|Oman|Qatar|Kuwait|Bahrain)\b',
    # Latin American countries
    r'\b(Brazil|Argentina|Mexico|Colombia|Venezuela|Peru|Chile|Ecuador|Bolivia|Uruguay|Paraguay)\b',
]

def _normalize_text(text: str) -> str:
    """Normalize text for pattern matching"""
    if not text:
        return ""
    try:
        # Convert to ASCII and normalize whitespace
        normalized = unidecode(text.strip())
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized
    except Exception as e:
        logger.debug(f"[LocationService] Text normalization failed: {e}")
        return text.strip()

def _titlecase(s: str) -> str:
    """Title case with proper handling"""
    if not s:
        return ""
    try:
        return " ".join(word.capitalize() for word in s.strip().split())
    except Exception as e:
        logger.debug(f"[LocationService] Title case failed: {e}")
        return s

def _validate_country(country: str) -> bool:
    """Validate if country exists in our location data"""
    try:
        location_data = _get_location_data()
        countries = location_data.get('countries', {})
        
        # Check exact match (normalized)
        country_lower = country.lower().strip()
        if country_lower in countries:
            return True
            
        # Check if it's a country value (canonical name)
        for country_value in countries.values():
            if country_lower == country_value.lower():
                return True
                
        return False
    except Exception as e:
        logger.debug(f"[LocationService] Country validation failed for '{country}': {e}")
        return False

def _get_canonical_country(country: str) -> Optional[str]:
    """Get canonical country name from location data"""
    try:
        location_data = _get_location_data()
        countries = location_data.get('countries', {})
        
        country_lower = country.lower().strip()
        
        # Direct lookup
        if country_lower in countries:
            return countries[country_lower]
            
        # Reverse lookup by canonical name
        for key, canonical in countries.items():
            if country_lower == canonical.lower():
                return canonical
                
        return None
    except Exception as e:
        logger.debug(f"[LocationService] Canonical country lookup failed for '{country}': {e}")
        return None

def _get_city_country(city: str) -> Optional[str]:
    """Get country for a city from location data"""
    try:
        location_data = _get_location_data()
        cities = location_data.get('cities', {})
        
        city_lower = city.lower().strip()
        
        if city_lower in cities:
            city_info = cities[city_lower]
            if isinstance(city_info, dict) and 'country' in city_info:
                country_key = city_info['country']
                # Convert country key to canonical name
                canonical_country = _get_canonical_country(country_key)
                return canonical_country or country_key.title()
                
        return None
    except Exception as e:
        logger.debug(f"[LocationService] City country lookup failed for '{city}': {e}")
        return None

def _extract_with_patterns(text: str) -> LocationResult:
    """Extract location using regex patterns with enhanced error handling"""
    if not text:
        return LocationResult()
    
    try:
        normalized = _normalize_text(text)
        
        # Try city, country patterns first
        for pattern in CITY_COUNTRY_PATTERNS:
            try:
                match = re.search(pattern, normalized, re.IGNORECASE)
                if match and len(match.groups()) >= 2:
                    city = _titlecase(match.group(1))
                    country = _titlecase(match.group(2))
                    
                    # Validate against our location data
                    if len(city) > 2 and len(country) > 2:
                        canonical_country = _get_canonical_country(country)
                        if canonical_country:
                            return LocationResult(
                                city=city,
                                country=canonical_country,
                                location_method='pattern_match',
                                location_confidence='high'
                            )
            except Exception as e:
                logger.debug(f"[LocationService] Pattern matching error: {e}")
                continue
        
        # Try city-only patterns (like "PARIS:" or "LONDON -")
        for pattern in CITY_ONLY_PATTERNS:
            try:
                match = re.search(pattern, normalized, re.IGNORECASE)
                if match:
                    city = _titlecase(match.group(1))
                    if len(city) > 2:
                        # Check if it's a known city in our data
                        country = _get_city_country(city)
                        if country:
                            return LocationResult(
                                city=city,
                                country=country,
                                location_method='known_city',
                                location_confidence='high'
                            )
            except Exception as e:
                logger.debug(f"[LocationService] City pattern matching error: {e}")
                continue
        
        # Try country-only patterns
        for pattern in COUNTRY_PATTERNS:
            try:
                match = re.search(pattern, normalized, re.IGNORECASE)
                if match:
                    country = _titlecase(match.group(1))
                    canonical_country = _get_canonical_country(country)
                    if canonical_country:
                        return LocationResult(
                            country=canonical_country,
                            location_method='pattern_match',
                            location_confidence='medium'
                        )
            except Exception as e:
                logger.debug(f"[LocationService] Country pattern matching error: {e}")
                continue
        
        return LocationResult()
        
    except Exception as e:
        logger.error(f"[LocationService] Pattern extraction failed: {e}")
        return LocationResult()

def _check_known_cities(text: str) -> LocationResult:
    """Check for known cities in text using expanded location data"""
    if not text:
        return LocationResult()
    
    try:
        normalized = _normalize_text(text).lower()
        location_data = _get_location_data()
        cities = location_data.get('cities', {})
        
        # Score cities by match quality and length (prefer longer, more specific names)
        matches = []
        
        for city_name, city_info in cities.items():
            # Look for city name as whole word
            pattern = r'\b' + re.escape(city_name) + r'\b'
            if re.search(pattern, normalized):
                # Score based on city name length (longer = more specific)
                score = len(city_name)
                matches.append((score, city_name, city_info))
        
        if matches:
            # Sort by score (highest first) and take the best match
            matches.sort(reverse=True)
            _, best_city_name, city_info = matches[0]
            
            if isinstance(city_info, dict) and 'country' in city_info:
                country_key = city_info['country']
                canonical_country = _get_canonical_country(country_key)
                country = canonical_country or country_key.title()
                
                return LocationResult(
                    city=_titlecase(best_city_name),
                    country=country,
                    location_method='known_city',
                    location_confidence='high'
                )
        
        return LocationResult()
        
    except Exception as e:
        logger.error(f"[LocationService] Known cities check failed: {e}")
        return LocationResult()

def detect_location(text: str = "", title: str = "") -> LocationResult:
    """
    Main entry point for deterministic location extraction with robust error handling.
    
    Args:
        text: Article text/summary
        title: Article title
        
    Returns:
        LocationResult with extracted location data
    """
    try:
        combined_text = f"{title} {text}".strip()
        
        if not combined_text:
            return LocationResult()

        # Heuristic: elevate disruption/causal locations in clauses like
        # "... as Portugal national strike disrupts ..." or "due to <GPE> protest".
        causal_match = re.search(r"(?:as|due to|after)\s+([A-Z][A-Za-z\-\s]{2,})\s+(?:strike|protest|disruption|closure|unrest)", combined_text, re.IGNORECASE)
        if causal_match:
            place_token = causal_match.group(1).strip()
            canonical_country = _get_canonical_country(place_token)
            if canonical_country:
                return LocationResult(country=canonical_country, location_method='causal_clause', location_confidence='medium')
            city_country = _get_city_country(place_token)
            if city_country:
                return LocationResult(city=_titlecase(place_token), country=city_country, location_method='causal_clause', location_confidence='medium')
        
        # Try pattern-based extraction first (most reliable)
        result = _extract_with_patterns(combined_text)
        if result.country:
            logger.debug(f"[LocationService] Pattern match: {result.city}, {result.country}")
            return result
        
        # Try known cities
        result = _check_known_cities(combined_text)
        if result.country:
            logger.debug(f"[LocationService] Known city match: {result.city}, {result.country}")
            return result
        
        # No deterministic match found
        logger.debug(f"[LocationService] No deterministic match for: {title[:80]}")
        return LocationResult(location_method='none', location_confidence='none')
        
    except Exception as e:
        logger.error(f"[LocationService] Location extraction failed: {e}")
        return LocationResult(location_method='error', location_confidence='none')

def is_location_ambiguous(text: str = "", title: str = "") -> bool:
    """
    Determine if a location string needs Moonshot LLM processing with enhanced detection.
    Returns True if ambiguous/complex, False if deterministic methods suffice.
    """
    try:
        combined_text = f"{title} {text}".strip()
        
        if not combined_text:
            return False
        
        # Try deterministic extraction first
        location = detect_location(combined_text)
        
        # If we got a confident result, not ambiguous
        if location.city and location.country and location.location_confidence == "high":
            return False
        
        # Check for complexity indicators that suggest LLM needed
        ambiguous_patterns = [
            r'\b(?:near|close to|around|vicinity of)\b',  # Proximity indicators
            r'\b(?:several|multiple|various)\s+(?:locations|places|areas)\b',  # Multiple locations
            r'\b(?:unconfirmed|reported|alleged)\s+location\b',  # Uncertainty
            r'\b(?:somewhere in|area of|region of)\b',  # Vague location
            r'[,;]\s*(?:and|or)\s*[A-Z]',  # Multiple places separated by conjunctions
            r'\b(?:between|across|spanning)\s+[A-Z]',  # Geographic spans
            r'\b(?:border|frontier|crossing)\b',  # Border areas
            r'\b(?:remote|rural|isolated)\s+(?:area|region|village)\b',  # Remote locations
        ]
        
        for pattern in ambiguous_patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                return True
        
        # If deterministic methods failed and no obvious complexity, might need LLM
        if not location.city and not location.country:
            # Check if text contains potential location words that we couldn't parse
            potential_location_words = re.findall(r'\b[A-Z][a-zA-Z]{3,}\b', combined_text)
            if len(potential_location_words) > 3:  # Many capitalized words suggest locations
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"[LocationService] Ambiguity check failed: {e}")
        return True  # Default to ambiguous on error

def enhance_geographic_query(region: str) -> dict:
    """
    Enhanced geographic parameter handling using dynamic intelligence.
    Returns a dict with country, city, and region parameters.
    """
    try:
        # Use our deterministic location detection first
        location_result = detect_location(region)
        
        geo_params = {
            'country': location_result.country,
            'city': location_result.city,
            'region': region  # Always preserve original region
        }
        
        # If we have high confidence results, use them
        if location_result.location_confidence == "high":
            return geo_params
        
        # For medium/low confidence or missing data, keep original region
        # but include any detected components
        if not geo_params['country'] and not geo_params['city']:
            geo_params['region'] = region
        
        return geo_params
        
    except Exception as e:
        logger.warning(f"[LocationService] Geographic enhancement failed for '{region}': {e}")
        # Return minimal structure on error
        return {
            'country': None,
            'city': None,
            'region': region
        }

def get_location_stats() -> dict:
    """Get statistics about loaded location data for monitoring"""
    try:
        location_data = _get_location_data()
        
        countries_count = len(location_data.get('countries', {}))
        cities_count = len(location_data.get('cities', {}))
        regions_count = len(location_data.get('regions', {}))
        
        # Count cities by region
        cities = location_data.get('cities', {})
        region_distribution = {}
        for city_info in cities.values():
            if isinstance(city_info, dict) and 'region' in city_info:
                region = city_info['region']
                region_distribution[region] = region_distribution.get(region, 0) + 1
        
        return {
            'countries': countries_count,
            'cities': cities_count,
            'regions': regions_count,
            'region_distribution': region_distribution,
            'data_loaded': _LOCATION_KEYWORDS_LOADED,
            'data_available': _LOCATION_KEYWORDS is not None
        }
        
    except Exception as e:
        logger.error(f"[LocationService] Stats collection failed: {e}")
        return {
            'countries': 0,
            'cities': 0,
            'regions': 0,
            'region_distribution': {},
            'data_loaded': False,
            'data_available': False,
            'error': str(e)
        }