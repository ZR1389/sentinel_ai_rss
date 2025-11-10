# alert_builder_refactored.py — Clean, testable alert building components
# Refactored from the monolithic _build_alert_from_entry function
# Self-contained to avoid circular imports

from __future__ import annotations
import time
import logging
import hashlib
import os
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

try:
    from unidecode import unidecode
except ImportError:
    def unidecode(s: str) -> str:  # type: ignore
        return s

try:
    from langdetect import detect
except ImportError:
    def detect(_: str) -> str:  # type: ignore
        return "en"

logger = logging.getLogger("alert_builder")

# Configuration
FRESHNESS_DAYS = int(os.getenv("FRESHNESS_DAYS", "14"))
GEOCODE_ENABLED = os.getenv("GEOCODE_ENABLED", "true").lower() == "true"

# City defaults mapping  
CITY_DEFAULTS = {
    "london": "United Kingdom",
    "paris": "France", 
    "madrid": "Spain",
    "rome": "Italy",
    "berlin": "Germany",
    "moscow": "Russia",
    "beijing": "China",
    "tokyo": "Japan",
    "sydney": "Australia",
    "toronto": "Canada",
    "vancouver": "Canada",
    "new york": "United States",
    "washington": "United States",
    "los angeles": "United States",
    "chicago": "United States",
    "san francisco": "United States",
    "boston": "United States",
    "atlanta": "United States",
    "miami": "United States",
    "houston": "United States",
    "mexico city": "Mexico",
    "singapore": "Singapore",
    "hong kong": "Hong Kong",
    "tel aviv": "Israel",
    "tehran": "Iran, Islamic Republic of",
    "minsk": "Belarus",
}

# Region mappings (simplified)
REGION_MAP = {
    "united states": "north_america",
    "canada": "north_america",
    "mexico": "north_america",
    "united kingdom": "europe",
    "france": "europe",
    "germany": "europe",
    "spain": "europe",
    "italy": "europe",
    "china": "asia",
    "japan": "asia",
    "singapore": "asia",
    "australia": "oceania",
    "russia": "europe",
}

# ===== UTILITY FUNCTIONS =====

def _apply_city_defaults(city: Optional[str], country: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Apply default countries for major cities"""
    if city and (not country or country.strip() == ""):
        ck = city.lower().strip()
        if ck in CITY_DEFAULTS:
            logger.debug("[alert_builder] CITY_DEFAULTS filled country: '%s' -> '%s'", city, CITY_DEFAULTS[ck])
            return city, CITY_DEFAULTS[ck]
    return city, country

def _map_country_to_region(country: Optional[str]) -> Optional[str]:
    """Map country to region"""
    if not country:
        return None
    return REGION_MAP.get(country.lower())

def _titlecase(s: str) -> str:
    """Convert to title case"""
    return " ".join(w.capitalize() for w in s.split())

def _uuid_for(source: str, title: str, link: str) -> str:
    """Generate UUID for alert"""
    blob = f"{source}::{title}::{link}"
    return hashlib.md5(blob.encode("utf-8")).hexdigest()

def _extract_source(url: str) -> str:
    """Extract source from URL"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or "unknown"
    except Exception:
        return "unknown"

def _now_utc() -> datetime:
    """Get current UTC datetime"""
    return datetime.now(timezone.utc)

def _normalize_summary(title: str, summary: str) -> str:
    """Normalize summary text"""
    if not summary or summary.strip() == "":
        return title or ""
    summary = summary.replace("\n", " ").replace("\r", "").strip()
    # Remove title if it appears at start of summary
    if summary.lower().startswith((title or "").lower()):
        summary = summary[len(title):].strip()
        if summary.startswith(":"):
            summary = summary[1:].strip()
    return summary or title or ""

def _safe_lang(text: str) -> str:
    """Safe language detection"""
    try:
        return detect(text or "")[:2]
    except Exception:
        return "en"

def _first_sentence(text: str) -> str:
    """Extract first sentence"""
    if not text:
        return ""
    sentences = text.replace("\n", " ").split(".")
    first = sentences[0].strip() if sentences else ""
    return first[:200] if first else ""

def _auto_tags(text: str) -> List[str]:
    """Auto-generate tags from text"""
    t = (text or "").lower()
    tags: List[str] = []
    
    tag_keywords = {
        "cyber_it": ["ransomware","phishing","malware","breach","ddos","credential","cve","zero-day","exploit","vpn","mfa"],
        "civil_unrest": ["protest","riot","clash","strike","looting","roadblock"],
        "physical_safety": ["shooting","stabbing","robbery","assault","kidnap","kidnapping","murder","attack"],
        "geopolitical": ["election","government","diplomatic","sanctions","treaty","military","war"],
        "natural_disaster": ["earthquake","flood","hurricane","tornado","wildfire","tsunami"],
        "health": ["outbreak","pandemic","epidemic","disease","virus","vaccine"],
        "economic": ["inflation","recession","market","stock","currency","trade"]
    }
    
    for tag, keywords in tag_keywords.items():
        if any(kw in t for kw in keywords):
            tags.append(tag)
    
    return tags[:5]  # Limit to 5 tags

# ===== CORE DATA CLASSES =====

@dataclass
class AlertMetadata:
    """Basic alert metadata extracted from entry"""
    uuid: str
    title: str
    summary: str
    link: str
    source: str
    published: datetime
    language: str
    text_blob: str

@dataclass  
class LocationResult:
    """Result of location detection"""
    city: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_method: str = "none"
    location_confidence: str = "none"
    needs_batch_processing: bool = False

# ===== MODULAR COMPONENTS =====

class ContentValidator:
    """Validates content against filtering rules"""
    
    @staticmethod
    def should_process_entry(entry: Dict[str, Any], cutoff_days: int) -> bool:
        """Basic entry validation"""
        published = entry.get("published")
        if published:
            cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
            if published < cutoff:
                return False
        return True
    
    @staticmethod
    async def passes_keyword_filter(metadata: AlertMetadata, client) -> Tuple[bool, str]:
        """Check if content passes keyword filtering"""
        try:
            # Import the keyword matching function
            from rss_processor import _kw_decide, _fetch_article_fulltext
            
            # First try with title + summary
            text_blob = f"{metadata.title}\n{metadata.summary}"
            hit, km = _kw_decide(metadata.title, text_blob)
            if hit:
                return True, km
            
            # Try with full text if available
            fulltext = await _fetch_article_fulltext(client, metadata.link)
            if fulltext:
                text_blob = f"{metadata.title}\n{metadata.summary}\n{fulltext}"
                hit, km = _kw_decide(metadata.title, text_blob)
                if hit:
                    # Update metadata with enhanced text
                    metadata.text_blob = text_blob
                    return True, km
            
            return False, ""
            
        except ImportError:
            # If keyword filtering not available, allow everything
            logger.debug("Keyword filtering not available, allowing all content")
            return True, "no_filter"
        except Exception as e:
            logger.error(f"Keyword filtering failed: {e}")
            return False, ""

class SourceTagParser:
    """Parses location information from source tags"""
    
    @staticmethod
    def extract_city_from_tag(tag: Optional[str]) -> Optional[str]:
        """Extract city from local: tag"""
        if tag and tag.startswith("local:"):
            return tag.split("local:", 1)[1].strip()
        return None

    @staticmethod
    def extract_country_from_tag(tag: Optional[str]) -> Optional[str]:
        """Extract country from country: tag"""
        if tag and tag.startswith("country:"):
            return _titlecase(tag.split("country:", 1)[1].strip())
        return None

class LocationExtractor:
    """Extract location information from alerts"""
    
    def __init__(self, geocode_enabled: bool = GEOCODE_ENABLED):
        self.geocode_enabled = geocode_enabled
    
    async def extract_location(
        self, 
        metadata: AlertMetadata, 
        source_tag: Optional[str] = None,
        batch_mode: bool = False,
        client = None
    ) -> LocationResult:
        """
        Extract location using simplified hybrid approach.
        
        Strategy order:
        1. Try deterministic location detection (if available)
        2. Try source tag fallback
        3. Return basic result
        """
        # Strategy 1: Try deterministic location detection
        result = self._try_deterministic_location(metadata)
        if result.country:
            return self._enhance_with_geocoding(result)
        
        # Strategy 2: Try source tag fallback
        result = self._try_source_tag_location(source_tag)
        if result.country:
            return self._enhance_with_geocoding(result)
        
        # Strategy 3: Return empty result
        return LocationResult()
    
    def _try_deterministic_location(self, metadata: AlertMetadata) -> LocationResult:
        """Try fast deterministic location detection"""
        try:
            # Try to import the location service
            from location_service_consolidated import detect_location
            result = detect_location(text=metadata.summary, title=metadata.title)
            
            if result.country:
                return LocationResult(
                    city=result.city,
                    country=result.country,
                    region=result.region,
                    location_method=result.location_method,
                    location_confidence=result.location_confidence
                )
        except ImportError:
            logger.debug("location_service_consolidated not available")
        except Exception as e:
            logger.error(f"Deterministic location detection failed: {e}")
        
        return LocationResult()
    
    def _try_source_tag_location(self, source_tag: Optional[str]) -> LocationResult:
        """Extract location from source tags"""
        if not source_tag:
            return LocationResult()
        
        try:
            # Try city tag
            city_string = SourceTagParser.extract_city_from_tag(source_tag)
            if city_string:
                city, country = self._normalize_city_simple(city_string)
                city, country = _apply_city_defaults(city, country)
                
                # Check for country tag if no country from city
                if not country:
                    country = SourceTagParser.extract_country_from_tag(source_tag)
                
                if country:
                    region = _map_country_to_region(country)
                    return LocationResult(
                        city=city,
                        country=country,
                        region=region,
                        location_method="feed_tag",
                        location_confidence="low"
                    )
            
            # Try country tag only
            country = SourceTagParser.extract_country_from_tag(source_tag)
            if country:
                region = _map_country_to_region(country)
                return LocationResult(
                    country=country,
                    region=region,
                    location_method="feed_tag",
                    location_confidence="low"
                )
        
        except Exception as e:
            logger.error(f"Source tag location extraction failed: {e}")
        
        return LocationResult()
    
    def _normalize_city_simple(self, city_string: str) -> Tuple[Optional[str], Optional[str]]:
        """Simple city normalization"""
        if not city_string:
            return None, None
        
        # Handle "city, country" format
        if "," in city_string:
            parts = city_string.split(",", 1)
            city = parts[0].strip().title()
            country = parts[1].strip().title() if len(parts) > 1 else None
            return city, country
        else:
            return city_string.strip().title(), None
    
    def _enhance_with_geocoding(self, result: LocationResult) -> LocationResult:
        """Add geocoding if available"""
        if not self.geocode_enabled or not result.city:
            return result
        
        try:
            # Try to get coordinates
            from city_utils import get_city_coords
            latitude, longitude = get_city_coords(result.city, result.country)
            result.latitude = latitude
            result.longitude = longitude
        except ImportError:
            logger.debug("city_utils not available for geocoding")
        except Exception as e:
            logger.error(f"Geocoding failed: {e}")
        
        return result

class AlertBuilder:
    """Builds final alert dict from components"""
    
    @staticmethod
    def create_alert(
        metadata: AlertMetadata,
        location: LocationResult,
        kw_match: str,
        source_tag: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create final alert dictionary"""
        
        alert = {
            "uuid": metadata.uuid,
            "title": metadata.title,
            "summary": metadata.summary,
            "en_snippet": _first_sentence(unidecode(metadata.summary)),
            "link": metadata.link,
            "source": metadata.source,
            "published": metadata.published.replace(tzinfo=None),
            "tags": _auto_tags(metadata.text_blob),
            "region": location.region,
            "country": location.country,
            "city": location.city,
            "location_method": location.location_method,
            "location_confidence": location.location_confidence,
            "location_sharing": location.latitude is not None and location.longitude is not None,
            "language": metadata.language,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "kw_match": kw_match,
        }
        
        if source_tag:
            alert["source_tag"] = source_tag
            
        return alert

# ===== MAIN FACTORY FUNCTION =====

async def build_alert_from_entry_v2(
    entry: Dict[str, Any],
    source_url: str,
    client,
    source_tag: Optional[str] = None,
    batch_mode: bool = False
) -> Optional[Dict[str, Any]]:
    """
    REFACTORED: Clean, modular alert building.
    
    This replaces the original 250-line monolithic function with clean,
    testable components that avoid the deep nesting and complexity issues.
    """
    
    try:
        # 1. Basic validation
        if not ContentValidator.should_process_entry(entry, FRESHNESS_DAYS):
            return None
        
        # 2. Extract basic metadata
        title = entry.get("title", "")
        summary = _normalize_summary(title, entry.get("summary", ""))
        link = entry.get("link", "")
        published = entry.get("published") or _now_utc()
        source = _extract_source(source_url or link)
        uuid = _uuid_for(source, title, link)
        
        # Check for duplicate
        try:
            from rss_processor import fetch_one
            if fetch_one:
                exists = fetch_one("SELECT 1 FROM raw_alerts WHERE uuid=%s", (uuid,))
                if exists:
                    return None
        except Exception:
            pass
        
        text_blob = f"{title}\n{summary}"
        language = _safe_lang(text_blob)
        
        metadata = AlertMetadata(
            uuid=uuid,
            title=title,
            summary=summary,
            link=link,
            source=source,
            published=published,
            language=language,
            text_blob=text_blob
        )
        
        # 3. Keyword filtering
        passes_filter, kw_match = await ContentValidator.passes_keyword_filter(metadata, client)
        if not passes_filter:
            return None
        
        # 4. Location extraction
        extractor = LocationExtractor()
        location = await extractor.extract_location(metadata, source_tag, batch_mode, client)
        
        # 5. Build final alert
        alert = AlertBuilder.create_alert(metadata, location, kw_match, source_tag)
        
        return alert
        
    except Exception as e:
        logger.error(f"[REFACTORED] Alert building failed: {e}")
        return None
