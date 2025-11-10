"""
Consolidated location extraction service with deterministic methods.
Used as first pass before Moonshot batch processing for ambiguous cases.
"""
import re
import logging
from typing import Optional, Tuple, NamedTuple

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

# Common patterns for deterministic location extraction
CITY_COUNTRY_PATTERNS = [
    # "Event in City, Country"
    r'\b(?:in|at|near|from)\s+([A-Z][a-zA-Z\s]+),\s*([A-Z][a-zA-Z\s]+?)(?:\s|$|[,.!])',
    # "City, Country - description"
    r'^([A-Z][a-zA-Z\s]+),\s*([A-Z][a-zA-Z\s]+?)\s*[-–—]\s*',
    # (City, Country) format
    r'\(([A-Z][a-zA-Z\s]+),\s*([A-Z][a-zA-Z\s]+?)\)',
]

CITY_ONLY_PATTERNS = [
    # "CITY: description" or "CITY -" (all caps city names)
    r'^([A-Z]{3,})\s*[:–—-]\s*',
]

COUNTRY_PATTERNS = [
    # Country-specific phrases (known entities only)
    r'\b(United States|United Kingdom|South Korea|North Korea|Saudi Arabia|South Africa|New Zealand)\b',
    r'\b(USA|UK|US|UAE|EU)\b',
]

# Known countries for validation
KNOWN_COUNTRIES = {
    'united states', 'united kingdom', 'france', 'germany', 'italy', 'spain', 
    'russia', 'china', 'japan', 'india', 'australia', 'canada', 'mexico',
    'brazil', 'argentina', 'egypt', 'nigeria', 'south africa', 'kenya',
    'turkey', 'israel', 'saudi arabia', 'uae', 'iran', 'iraq', 'ukraine',
    'poland', 'netherlands', 'sweden', 'norway', 'denmark', 'belgium',
    'switzerland', 'austria', 'greece', 'portugal', 'ireland', 'finland'
}

# Known cities for high-confidence matching
MAJOR_CITIES = {
    'london': 'United Kingdom',
    'paris': 'France', 
    'berlin': 'Germany',
    'rome': 'Italy',
    'madrid': 'Spain',
    'moscow': 'Russia',
    'beijing': 'China',
    'tokyo': 'Japan',
    'mumbai': 'India',
    'delhi': 'India',
    'sydney': 'Australia',
    'melbourne': 'Australia',
    'toronto': 'Canada',
    'vancouver': 'Canada',
    'new york': 'United States',
    'los angeles': 'United States',
    'chicago': 'United States',
    'houston': 'United States',
    'miami': 'United States',
    'washington': 'United States',
    'san francisco': 'United States',
    'boston': 'United States',
    'mexico city': 'Mexico',
    'buenos aires': 'Argentina',
    'sao paulo': 'Brazil',
    'rio de janeiro': 'Brazil',
    'cairo': 'Egypt',
    'lagos': 'Nigeria',
    'johannesburg': 'South Africa',
    'nairobi': 'Kenya',
    'istanbul': 'Turkey',
    'dubai': 'United Arab Emirates',
    'riyadh': 'Saudi Arabia',
    'tel aviv': 'Israel',
    'jerusalem': 'Israel',
}

def _normalize_text(text: str) -> str:
    """Normalize text for pattern matching"""
    if not text:
        return ""
    # Convert to ASCII and normalize whitespace
    normalized = unidecode(text.strip())
    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized

def _titlecase(s: str) -> str:
    """Title case with proper handling"""
    if not s:
        return ""
    return " ".join(word.capitalize() for word in s.strip().split())

def _extract_with_patterns(text: str) -> LocationResult:
    """Extract location using regex patterns"""
    if not text:
        return LocationResult()
    
    normalized = _normalize_text(text)
    
    # Try city, country patterns first
    for pattern in CITY_COUNTRY_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            if len(match.groups()) >= 2:
                city = _titlecase(match.group(1))
                country = _titlecase(match.group(2))
                
                # Validate country against known list
                if len(city) > 2 and len(country) > 2 and country.lower() in KNOWN_COUNTRIES:
                    return LocationResult(
                        city=city,
                        country=country,
                        location_method='pattern_match',
                        location_confidence='high'
                    )
    
    # Try city-only patterns (like "PARIS:" or "LONDON -")
    for pattern in CITY_ONLY_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            city = _titlecase(match.group(1))
            if len(city) > 2:
                # Check if it's a known major city
                city_lower = city.lower()
                if city_lower in MAJOR_CITIES:
                    return LocationResult(
                        city=city,
                        country=MAJOR_CITIES[city_lower],
                        location_method='known_city',
                        location_confidence='high'
                    )
    
    # Try country-only patterns (specific known countries)
    for pattern in COUNTRY_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            country = _titlecase(match.group(1))
            if country.lower() in KNOWN_COUNTRIES:
                return LocationResult(
                    country=country,
                    location_method='pattern_match',
                    location_confidence='medium'
                )
    
    return LocationResult()

def _check_known_cities(text: str) -> LocationResult:
    """Check for known major cities in text"""
    if not text:
        return LocationResult()
    
    normalized = _normalize_text(text).lower()
    
    for city_name, country in MAJOR_CITIES.items():
        # Look for city name as whole word
        pattern = r'\b' + re.escape(city_name) + r'\b'
        if re.search(pattern, normalized):
            return LocationResult(
                city=_titlecase(city_name),
                country=country,
                location_method='known_city',
                location_confidence='high'
            )
    
    return LocationResult()

def detect_location(text: str = "", title: str = "") -> LocationResult:
    """
    Main entry point for deterministic location extraction.
    
    Args:
        text: Article text/summary
        title: Article title
        
    Returns:
        LocationResult with extracted location data
    """
    combined_text = f"{title} {text}".strip()
    
    if not combined_text:
        return LocationResult()
    
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
    return LocationResult(
        location_method='none',
        location_confidence='none'
    )

def is_location_ambiguous(text: str = "", title: str = "") -> bool:
    """
    Determine if a location string needs Moonshot LLM processing.
    Returns True if ambiguous/complex, False if deterministic methods suffice.
    """
    combined_text = f"{title} {text}".strip()
    
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
    ]
    
    for pattern in ambiguous_patterns:
        if re.search(pattern, combined_text, re.IGNORECASE):
            return True
    
    # If deterministic methods failed and no obvious complexity, still might need LLM
    if not location.city and not location.country:
        return True
    
    return False


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
        logger.warning(f"Geographic enhancement failed for '{region}': {e}")
        # Return minimal structure on error
        return {
            'country': None,
            'city': None,
            'region': region
        }