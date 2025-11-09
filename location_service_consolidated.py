# location_service_consolidated.py - Complete standalone location intelligence service
# v2025-11-09 - No external dependencies except standard libraries and optional packages

from __future__ import annotations
import json
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Set
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class LocationResult:
    """Standardized location detection result."""
    country: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_method: str = "unknown"
    location_confidence: str = "medium"  # none, low, medium, high
    raw_input: str = ""
    detected_entities: List[str] = field(default_factory=list)

class ConsolidatedLocationService:
    """
    Centralized location intelligence service with all detection methods.
    No external module dependencies - completely self-contained.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.location_keywords = self._load_location_keywords()
        self._nlp = None  # Lazy load spaCy
        self._llm_available = False
        self._setup_llm()
        
    def _load_location_keywords(self) -> Dict[str, Any]:
        """Load location keywords from JSON file."""
        try:
            keywords_file = Path(__file__).parent / "location_keywords.json"
            if keywords_file.exists():
                with open(keywords_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load location keywords: {e}")
        
        # Fallback basic keywords
        return {
            "countries": {
                "usa": "United States", "us": "United States", "america": "United States",
                "uk": "United Kingdom", "britain": "United Kingdom", "england": "United Kingdom",
                "canada": "Canada", "france": "France", "germany": "Germany", "spain": "Spain",
                "italy": "Italy", "japan": "Japan", "china": "China", "india": "India",
                "brazil": "Brazil", "méxico": "Mexico", "mexico": "Mexico", "australia": "Australia",
                "colombia": "Colombia", "nigeria": "Nigeria", "niger": "Niger", "russia": "Russia",
                "united states": "United States", "united kingdom": "United Kingdom"
            },
            "cities": {
                "new york": {"city": "New York", "country": "United States"},
                "london": {"city": "London", "country": "United Kingdom"},
                "paris": {"city": "Paris", "country": "France"},
                "tokyo": {"city": "Tokyo", "country": "Japan"},
                "berlin": {"city": "Berlin", "country": "Germany"},
                "sydney": {"city": "Sydney", "country": "Australia"},
                "toronto": {"city": "Toronto", "country": "Canada"},
                "mumbai": {"city": "Mumbai", "country": "India"},
                "bogota": {"city": "Bogotá", "country": "Colombia"},
                "bogotá": {"city": "Bogotá", "country": "Colombia"},
                "lagos": {"city": "Lagos", "country": "Nigeria"},
                "sao paulo": {"city": "São Paulo", "country": "Brazil"},
                "são paulo": {"city": "São Paulo", "country": "Brazil"}
            }
        }
    
    def _setup_llm(self):
        """Setup LLM router if available."""
        try:
            from llm_router import route_llm
            self._route_llm = route_llm
            self._llm_available = True
        except Exception:
            self._llm_available = False
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for consistent matching."""
        if not text:
            return ""
        import re
        # Convert to lowercase and remove extra whitespace
        normalized = re.sub(r'\s+', ' ', text.lower().strip())
        # Remove common punctuation but keep essential characters
        normalized = re.sub(r'[^\w\s\-\']', ' ', normalized)
        return re.sub(r'\s+', ' ', normalized).strip()
    
    def _normalize_country_name(self, country_name: str) -> Optional[str]:
        """Normalize country name using pycountry if available."""
        if not country_name:
            return None
        
        try:
            import pycountry
            # Try exact match first
            try:
                country = pycountry.countries.lookup(country_name)
                return country.name
            except LookupError:
                pass
            
            # Try fuzzy match
            normalized = self._normalize_text(country_name)
            for country in pycountry.countries:
                if normalized in self._normalize_text(country.name):
                    return country.name
                # Check common names and alternative names
                for attr in ['official_name', 'common_name']:
                    if hasattr(country, attr):
                        alt_name = getattr(country, attr)
                        if alt_name and normalized in self._normalize_text(alt_name):
                            return country.name
        except ImportError:
            pass
        
        # Fallback to basic normalization
        return country_name.strip().title() if country_name else None
    
    def _map_country_to_region(self, country: str) -> Optional[str]:
        """Map country to geographic region."""
        if not country:
            return None
        
        region_mapping = {
            # North America
            "United States": "North America", "Canada": "North America", "Mexico": "North America",
            # South America  
            "Brazil": "South America", "Argentina": "South America", "Colombia": "South America",
            "Chile": "South America", "Peru": "South America", "Venezuela": "South America",
            # Europe
            "United Kingdom": "Europe", "France": "Europe", "Germany": "Europe", "Spain": "Europe",
            "Italy": "Europe", "Russia": "Europe", "Poland": "Europe", "Netherlands": "Europe",
            # Asia
            "China": "Asia", "Japan": "Asia", "India": "Asia", "South Korea": "Asia",
            "Indonesia": "Asia", "Thailand": "Asia", "Vietnam": "Asia", "Philippines": "Asia",
            # Middle East
            "Saudi Arabia": "Middle East", "United Arab Emirates": "Middle East", "Iran": "Middle East",
            "Turkey": "Middle East", "Israel": "Middle East", "Iraq": "Middle East",
            # Africa
            "Nigeria": "Africa", "South Africa": "Africa", "Kenya": "Africa", "Egypt": "Africa",
            "Morocco": "Africa", "Ghana": "Africa", "Ethiopia": "Africa",
            # Oceania
            "Australia": "Oceania", "New Zealand": "Oceania"
        }
        
        return region_mapping.get(country)
    
    def detect_location_ner(self, text: str) -> LocationResult:
        """NER-based location detection using spaCy."""
        try:
            # Lazy load spaCy
            if self._nlp is None:
                try:
                    import spacy
                    self._nlp = spacy.load("en_core_web_sm")
                except Exception as e:
                    # Only log at debug level - spaCy is optional
                    self.logger.debug(f"spaCy not available: {e}")
                    return LocationResult(
                        location_method="ner_unavailable", 
                        location_confidence="none",
                        raw_input=text[:100]
                    )
            
            # Process text and extract location entities
            doc = self._nlp(text[:500])  # Limit text length for performance
            locations = [ent.text for ent in doc.ents if ent.label_ == "GPE"]
            
            if not locations:
                return LocationResult(
                    location_method="ner", 
                    location_confidence="none",
                    raw_input=text[:100]
                )
            
            # Take the first location found
            primary_raw = locations[0].strip()
            primary = self._normalize_text(primary_raw)
            
            # Check if it's a known country in our keywords
            if primary in self.location_keywords.get("countries", {}):
                country = self.location_keywords["countries"][primary]
                country = self._normalize_country_name(country)
                region = self._map_country_to_region(country)
                return LocationResult(
                    country=country, city=None, region=region,
                    location_method="ner", location_confidence="high",
                    raw_input=text[:100], detected_entities=[primary_raw]
                )
            
            # Check if it's a known city in our keywords
            if primary in self.location_keywords.get("cities", {}):
                city_data = self.location_keywords["cities"][primary]
                country = self._normalize_country_name(city_data.get("country"))
                region = self._map_country_to_region(city_data.get("country"))
                return LocationResult(
                    country=country, city=city_data.get("city"), region=region,
                    location_method="ner", location_confidence="high",
                    raw_input=text[:100], detected_entities=[primary_raw]
                )
            
            # Otherwise try to normalize as country name
            country_norm = self._normalize_country_name(primary_raw)
            confidence = "medium" if country_norm else "low"
            
            return LocationResult(
                country=country_norm, city=None, 
                region=self._map_country_to_region(country_norm),
                location_method="ner", location_confidence=confidence,
                raw_input=text[:100], detected_entities=[primary_raw]
            )
            
        except Exception as e:
            self.logger.error(f"NER location detection error: {e}")
            return LocationResult(
                location_method="ner_error", location_confidence="none",
                raw_input=text[:100]
            )
    
    def detect_location_keywords(self, text: str) -> LocationResult:
        """Keyword-based location detection."""
        try:
            if not self.location_keywords:
                return LocationResult(
                    location_method="keywords_unavailable", 
                    location_confidence="none",
                    raw_input=text[:100]
                )
            
            text_lower = self._normalize_text(text or "")
            
            # Check cities first (more specific) - prioritize longer matches
            city_matches = []
            for keyword, city_data in self.location_keywords.get("cities", {}).items():
                if keyword in text_lower:
                    city_matches.append((keyword, city_data, len(keyword)))
            
            if city_matches:
                # Sort by length (longer = more specific)
                keyword, city_data, _ = max(city_matches, key=lambda x: x[2])
                region = self._map_country_to_region(city_data.get("country"))
                return LocationResult(
                    country=city_data.get("country"), 
                    city=city_data.get("city"), 
                    region=region,
                    location_method="keywords", location_confidence="high",
                    raw_input=text[:100], detected_entities=[keyword]
                )
            
            # Check countries - prioritize longer matches
            country_matches = []
            for keyword, country in self.location_keywords.get("countries", {}).items():
                if keyword in text_lower:
                    country_matches.append((keyword, country, len(keyword)))
            
            if country_matches:
                # Sort by length (longer = more specific)
                keyword, country, _ = max(country_matches, key=lambda x: x[2])
                region = self._map_country_to_region(country)
                return LocationResult(
                    country=country, city=None, region=region,
                    location_method="keywords", location_confidence="high",
                    raw_input=text[:100], detected_entities=[keyword]
                )
            
            return LocationResult(
                location_method="keywords", location_confidence="none",
                raw_input=text[:100]
            )
            
        except Exception as e:
            self.logger.error(f"Keywords location detection error: {e}")
            return LocationResult(
                location_method="keywords_error", location_confidence="none",
                raw_input=text[:100]
            )
    
    def detect_location_llm(self, title: str, summary: str) -> LocationResult:
        """LLM-based location detection."""
        try:
            if not self._llm_available:
                return LocationResult(
                    location_method="llm_unavailable", 
                    location_confidence="none",
                    raw_input=f"{title[:50]}..."
                )
            
            # Check if this is worth using expensive LLM
            if not self._should_use_llm(title, summary):
                return LocationResult(
                    location_method="llm_skipped", 
                    location_confidence="none",
                    raw_input=f"{title[:50]}..."
                )
            
            prompt = f"""Extract the PRIMARY geographic location this news article is about.

Title: {title}
Summary: {summary[:300]}

Return ONLY a JSON object:
{{
    "country": "Country name or null",
    "city": "City name or null", 
    "region": "Geographic region (e.g., Europe, Middle East, Asia) or null"
}}

Rules:
- If article is about MULTIPLE countries, pick the PRIMARY one
- If article is about global/abstract topics, return all null
- Don't use the source domain - focus on article content
- Use standard country names in English"""

            messages = [{"role": "user", "content": prompt}]
            response, model_used = self._route_llm(messages, temperature=0)
            
            if not response:
                return LocationResult(
                    location_method="llm_no_response", 
                    location_confidence="none",
                    raw_input=f"{title[:50]}..."
                )
            
            # Parse LLM response
            try:
                resp = response.strip()
                if resp.startswith("```json"):
                    resp = resp[7:]
                if resp.startswith("```"):
                    resp = resp[3:]
                if resp.endswith("```"):
                    resp = resp[:-3]
                resp = resp.strip()
                
                result = json.loads(resp)
                country_norm = self._normalize_country_name(result.get("country"))
                
                return LocationResult(
                    country=country_norm,
                    city=result.get("city"),
                    region=result.get("region") or self._map_country_to_region(country_norm),
                    location_method=f"llm_{model_used}" if model_used else "llm",
                    location_confidence="medium" if country_norm else "low",
                    raw_input=f"{title[:50]}...",
                    detected_entities=[str(result)]
                )
                
            except json.JSONDecodeError as e:
                self.logger.error(f"LLM JSON parse error: {e}. Response: {response[:200]}")
                return LocationResult(
                    location_method="llm_parse_error", 
                    location_confidence="none",
                    raw_input=f"{title[:50]}..."
                )
                
        except Exception as e:
            self.logger.error(f"LLM location detection error: {e}")
            return LocationResult(
                location_method="llm_error", 
                location_confidence="none",
                raw_input=f"{title[:50]}..."
            )
    
    def _should_use_llm(self, title: str, summary: str) -> bool:
        """Determine if LLM should be used (expensive operation)."""
        abstract_keywords = [
            "climate change", "global warming", "study shows", "research finds",
            "scientists say", "world", "worldwide", "international study",
            "according to report", "new study"
        ]
        text_lower = f"{title} {summary}".lower()
        
        # Skip abstract/global topics
        if any(kw in text_lower for kw in abstract_keywords):
            return False
            
        # Skip very short articles  
        if len(title or "") < 20 or len(summary or "") < 50:
            return False
            
        return True
    
    def detect_location_coordinates(self, latitude: float, longitude: float) -> LocationResult:
        """Reverse geocode coordinates to location."""
        try:
            # Try to use a geocoding service if available
            # For now, return coordinates as-is
            return LocationResult(
                latitude=latitude, longitude=longitude,
                location_method="coordinates", location_confidence="high",
                raw_input=f"lat={latitude}, lon={longitude}"
            )
        except Exception as e:
            self.logger.error(f"Coordinate location detection error: {e}")
            return LocationResult(
                location_method="coordinates_error", location_confidence="none"
            )
    
    def _enhance_with_coordinates(self, result: LocationResult) -> LocationResult:
        """Enhance a location result with coordinates if city/country detected."""
        if result.latitude is not None and result.longitude is not None:
            # Already has coordinates
            return result
            
        if not result.city and not result.country:
            # No location to geocode
            return result
            
        try:
            # Try to get coordinates using city_utils
            from city_utils import get_city_coords
            
            lat, lon = get_city_coords(result.city, result.country)
            if lat is not None and lon is not None:
                # Create enhanced result with coordinates
                enhanced_result = LocationResult(
                    country=result.country,
                    city=result.city, 
                    region=result.region,
                    latitude=lat,
                    longitude=lon,
                    location_method=f"{result.location_method}_geocoded",
                    location_confidence=result.location_confidence,
                    raw_input=result.raw_input,
                    detected_entities=result.detected_entities
                )
                self.logger.debug(f"Enhanced {result.city}, {result.country} with coordinates: {lat:.4f}, {lon:.4f}")
                return enhanced_result
                
        except Exception as e:
            self.logger.debug(f"Failed to enhance with coordinates: {e}")
            
        return result
    
    def detect_location_database(self, query: str) -> LocationResult:
        """Query database for location information."""
        try:
            # Try to connect to database and query for location patterns
            from db_utils import fetch_one
            
            # Look for similar location patterns in existing data
            sql = """
            SELECT country, city, region, COUNT(*) as frequency 
            FROM alerts 
            WHERE (title ILIKE %s OR gpt_summary ILIKE %s)
              AND (country IS NOT NULL OR city IS NOT NULL)
            GROUP BY country, city, region
            ORDER BY frequency DESC
            LIMIT 1
            """
            
            search_pattern = f"%{query}%"
            row = fetch_one(sql, (search_pattern, search_pattern))
            
            if row:
                country, city, region, frequency = row
                confidence = "high" if frequency > 10 else "medium" if frequency > 3 else "low"
                
                return LocationResult(
                    country=country, city=city, region=region,
                    location_method="database", location_confidence=confidence,
                    raw_input=query[:100]
                )
            
            return LocationResult(
                location_method="database", location_confidence="none",
                raw_input=query[:100]
            )
            
        except Exception as e:
            # Only log at debug level to avoid spam when DB unavailable
            self.logger.debug(f"Database location detection failed: {e}")
            return LocationResult(
                location_method="database_error", location_confidence="none",
                raw_input=query[:100]
            )
    
    def detect_location_comprehensive(
        self, 
        text: str, 
        title: str = "", 
        latitude: Optional[float] = None, 
        longitude: Optional[float] = None
    ) -> LocationResult:
        """
        Comprehensive location detection using all available methods.
        Priority: Coordinates > Database > NER > Keywords > LLM
        """
        full_text = f"{title} {text}".strip()
        
        # 1. Coordinates (highest confidence)
        if latitude is not None and longitude is not None:
            coord_result = self.detect_location_coordinates(latitude, longitude)
            if coord_result.location_confidence in ["high", "medium"]:
                return coord_result
        
        # 2. Database patterns (learned intelligence)
        db_result = self.detect_location_database(full_text)
        if db_result.location_confidence in ["high", "medium"]:
            return db_result
        
        # 3. NER (fast, accurate for entities)
        if len(full_text) > 10:
            ner_result = self.detect_location_ner(full_text)
            if ner_result.location_confidence in ["high", "medium"]:
                return self._enhance_with_coordinates(ner_result)
        
        # 4. Keywords (fast, reliable for known terms)
        keyword_result = self.detect_location_keywords(full_text)
        if keyword_result.location_confidence in ["high", "medium"]:
            return self._enhance_with_coordinates(keyword_result)
        
        # 5. LLM (expensive, last resort)
        if title and len(title) > 10:
            llm_result = self.detect_location_llm(title, text)
            if llm_result.location_confidence in ["high", "medium"]:
                return self._enhance_with_coordinates(llm_result)
        
        # No location detected
        return LocationResult(
            location_method="comprehensive_none", 
            location_confidence="none",
            raw_input=full_text[:100]
        )
    
    def _select_best_result(self, result1: LocationResult, result2: LocationResult) -> LocationResult:
        """Select the best result between two LocationResults."""
        confidence_order = {"high": 3, "medium": 2, "low": 1, "none": 0}
        
        conf1 = confidence_order.get(result1.location_confidence, 0)
        conf2 = confidence_order.get(result2.location_confidence, 0)
        
        if conf1 > conf2:
            return result1
        elif conf2 > conf1:
            return result2
        else:
            # Same confidence, prefer more specific methods
            method_priority = {
                "coordinates": 5, "database": 4, "ner": 3, 
                "keywords": 2, "llm": 1
            }
            prio1 = method_priority.get(result1.location_method.split('_')[0], 0)
            prio2 = method_priority.get(result2.location_method.split('_')[0], 0)
            
            return result1 if prio1 >= prio2 else result2
    
    def enhance_geographic_query(self, region: Optional[str]) -> Dict[str, Optional[str]]:
        """Enhanced geographic parameter handling for database queries."""
        if not region:
            return {"country": None, "city": None, "region": None}
        
        try:
            result = self.detect_location_database(region)
            
            return {
                "country": result.country,
                "city": result.city, 
                "region": result.region or region
            }
        except Exception as e:
            self.logger.warning(f"Geographic query enhancement failed: {e}")
            return {"country": None, "city": None, "region": region}

# Global service instance
_location_service_instance: Optional[ConsolidatedLocationService] = None

def get_location_service() -> ConsolidatedLocationService:
    """Get global consolidated location service instance."""
    global _location_service_instance
    if _location_service_instance is None:
        _location_service_instance = ConsolidatedLocationService()
    return _location_service_instance

def detect_location(
    text: str, 
    title: str = "", 
    latitude: Optional[float] = None, 
    longitude: Optional[float] = None
) -> LocationResult:
    """
    Main entry point for location detection.
    
    Args:
        text: Main text to analyze
        title: Optional title/headline
        latitude: Optional latitude coordinate
        longitude: Optional longitude coordinate
        
    Returns:
        LocationResult with detected location information
    """
    service = get_location_service()
    return service.detect_location_comprehensive(text, title, latitude, longitude)

def enhance_geographic_query(region: Optional[str]) -> Dict[str, Optional[str]]:
    """Enhance geographic query parameters."""
    service = get_location_service()
    return service.enhance_geographic_query(region)
