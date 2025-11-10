# location_extractor.py – Production-grade location extraction
from __future__ import annotations
import asyncio
import re
import json
import logging
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass

from config import CONFIG
from metrics import METRICS

# Import circuit breaker
try:
    from circuit_breaker import MOONSHOT_CB
except ImportError:
    from moonshot_circuit_breaker import get_moonshot_circuit_breaker
    MOONSHOT_CB = get_moonshot_circuit_breaker()

# Import the circuit breaker exception
try:
    from circuit_breaker import CircuitBreakerOpen
except ImportError:
    # Fallback if exception not defined
    class CircuitBreakerOpen(Exception):
        def __init__(self, message: str, retry_after: float = 0):
            super().__init__(message)
            self.retry_after = retry_after

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class LocationResult:
    """Immutable location extraction result."""
    city: Optional[str]
    country: Optional[str]
    region: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    method: str
    confidence: str  # "high", "medium", "low", "none"
    pending: bool = False

class LocationExtractor:
    """Thread-safe location extraction with Moonshot batching."""
    
    def __init__(self):
        self._batch_queue: asyncio.Queue[Tuple[Dict[str, Any], str, str, asyncio.Future]] = asyncio.Queue()
        self._batch_task: Optional[asyncio.Task] = None
        self._flush_interval = 30.0  # seconds
        self._running = False
        
        # Load location keywords once
        self.location_keywords = self._load_location_keywords()
        
        # Compile regex patterns
        self._local_tag_pattern = re.compile(r"^local:(.+)$")
        self._country_tag_pattern = re.compile(r"^country:(.+)$")
    
    def _load_location_keywords(self) -> Dict[str, Any]:
        """Load location keywords from JSON."""
        try:
            with open(CONFIG.threat_keywords_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load location_keywords.json: {e}")
            return {"countries": {}, "cities": {}, "regions": {}}
    
    async def start(self):
        """Start the background batch processing task."""
        if self._running:
            return
        self._running = True
        self._batch_task = asyncio.create_task(self._batch_processor())
        logger.info("[LocationExtractor] Started background batch processor")
    
    async def stop(self):
        """Stop the extractor and process remaining batches."""
        if not self._running:
            return
        self._running = False
        if self._batch_task:
            # Trigger one final flush
            await self._batch_processor()
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        logger.info("[LocationExtractor] Stopped")
    
    @METRICS.timer("location_extraction")
    async def extract_location(
        self,
        title: str,
        text: str,
        source_tag: Optional[str],
    ) -> LocationResult:
        """
        Extract location using deterministic methods first, fallback to Moonshot.
        """
        combined_text = f"{title}\n{text}"
        
        # 1. Try deterministic extraction
        try:
            from location_service_consolidated import detect_location
            result = detect_location(text=text, title=title)
            
            if result.country:  # Success
                lat, lon = await self._geocode_if_needed(result.city, result.country)
                return LocationResult(
                    city=result.city,
                    country=result.country,
                    region=result.region,
                    latitude=lat,
                    longitude=lon,
                    method=result.location_method,
                    confidence=result.location_confidence,
                )
        except Exception as e:
            logger.error(f"Deterministic location extraction failed: {e}", exc_info=True)
        
        # 2. Check if Moonshot is needed
        if self._should_use_moonshot(combined_text, source_tag):
            return await self._queue_for_batch(title, text, source_tag or "")
        
        # 3. Fallback to feed tag parsing
        city, country = self._parse_source_tag(source_tag)
        if city or country:
            lat, lon = await self._geocode_if_needed(city, country)
            region = self._map_country_to_region(country) if country else None
            return LocationResult(
                city=city,
                country=country,
                region=region,
                latitude=lat,
                longitude=lon,
                method="feed_tag",
                confidence="low",
            )
        
        # 4. Final fallback
        return LocationResult(
            city=None,
            country=None,
            region=None,
            latitude=None,
            longitude=None,
            method="none",
            confidence="none",
        )
    
    def _should_use_moonshot(self, text: str, source_tag: Optional[str]) -> bool:
        """Heuristic to determine if Moonshot is needed."""
        if not CONFIG.location_batch_threshold:
            return False
        
        # Check for critical domains
        try:
            from risk_shared import detect_domains
            domains = detect_domains(text)
            if "travel_mobility" in domains or "civil_unrest" in domains:
                return True
        except Exception:
            pass
        
        # Check for ambiguous location indicators
        text_lower = text.lower()
        location_hints = any(word in text_lower for word in [
            "in ", "at ", "from ", "near ", "police", "authorities",
            "local", "regional", "government", "officials"
        ])
        
        # If feed tag suggests location but we didn't find one
        return location_hints and not (source_tag and (":" in source_tag))
    
    async def _queue_for_batch(
        self,
        title: str,
        text: str,
        source_tag: str,
    ) -> LocationResult:
        """Queue item for Moonshot batch processing."""
        future = asyncio.Future()
        await self._batch_queue.put(({"title": title, "summary": text}, source_tag, text, future))
        
        # Return pending result
        return LocationResult(
            city=None,
            country=None,
            region=None,
            latitude=None,
            longitude=None,
            method="moonshot_pending",
            confidence="pending",
            pending=True,
        )
    
    async def _batch_processor(self):
        """Background task to process location batches."""
        last_flush = asyncio.get_event_loop().time()
        
        while self._running or not self._batch_queue.empty():
            try:
                # Wait for batch threshold or flush interval
                current_time = asyncio.get_event_loop().time()
                time_since_flush = current_time - last_flush
                
                if (
                    self._batch_queue.qsize() >= CONFIG.location_batch_threshold
                    or (time_since_flush >= self._flush_interval and not self._batch_queue.empty())
                ):
                    await self._flush_batch()
                    last_flush = current_time
                else:
                    # Sleep briefly to avoid busy-waiting
                    await asyncio.sleep(0.1)
            
            except Exception as e:
                logger.error(f"Batch processor error: {e}", exc_info=True)
                METRICS.increment("location_batch_errors")
    
    async def _flush_batch(self):
        """Flush current batch to Moonshot."""
        batch: List[Tuple[Dict[str, Any], str, str, asyncio.Future]] = []
        
        # Collect up to threshold items
        while len(batch) < CONFIG.location_batch_threshold and not self._batch_queue.empty():
            try:
                item = self._batch_queue.get_nowait()
                batch.append(item)
            except asyncio.QueueEmpty:
                break
        
        if not batch:
            return
        
        logger.info(f"[LocationExtractor] Flushing batch of {len(batch)} items to Moonshot")
        METRICS.increment("location_batches_sent", len(batch))
        
        try:
            results = await MOONSHOT_CB.call(self._call_moonshot, batch)
            await self._apply_batch_results(batch, results)
        except Exception as e:
            logger.error(f"Batch flush failed: {e}", exc_info=True)
            METRICS.increment("location_batch_failures")
            # Fail all pending futures
            for _, _, _, future in batch:
                if not future.done():
                    future.set_exception(e)
    
    async def _call_moonshot(self, batch: List[Tuple[Dict, str, str, asyncio.Future]]) -> Dict[str, Dict]:
        """Call Moonshot through circuit breaker."""
        from moonshot_client import MoonshotClient
        
        prompt = self._build_prompt(batch)
        
        async def _moonshot_call():
            moonshot = MoonshotClient()
            return await moonshot.acomplete(
                model="moonshot-v1-8k",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1500,
            )
        
        try:
            response = await MOONSHOT_CB.call(_moonshot_call)
            return self._parse_response(response, batch)
        except CircuitBreakerOpen as e:
            logger.error(f"[LocationExtractor] Moonshot circuit breaker open: {e}")
            METRICS.increment("moonshot_circuit_breaker_open")
            raise
    
    async def _apply_batch_results(
        self,
        batch: List[Tuple[Dict[str, Any], str, str, asyncio.Future]],
        results: Dict[str, Dict[str, Any]],
    ):
        """Apply Moonshot results to pending futures."""
        for entry, source_tag, uuid, future in batch:
            if uuid in results:
                item = results[uuid]
                city = item.get("city")
                country = item.get("country")
                region = item.get("region")
                
                # Geocode if possible
                lat, lon = await self._geocode_if_needed(city, country)
                
                result = LocationResult(
                    city=city,
                    country=country,
                    region=region,
                    latitude=lat,
                    longitude=lon,
                    method="moonshot_batch",
                    confidence="medium" if item.get("confidence", 0) > 0.7 else "low",
                )
                
                if not future.done():
                    future.set_result(result)
            else:
                # Moonshot didn't return this item
                if not future.done():
                    future.set_result(LocationResult(
                        city=None,
                        country=None,
                        region=None,
                        latitude=None,
                        longitude=None,
                        method="moonshot_failed",
                        confidence="none",
                    ))
    
    async def _geocode_if_needed(
        self,
        city: Optional[str],
        country: Optional[str],
    ) -> Tuple[Optional[float], Optional[float]]:
        """Geocode city/country if enabled."""
        if not CONFIG.geocode_enabled or not city:
            return None, None
        
        try:
            from city_utils import get_city_coords
            return get_city_coords(city, country)
        except Exception as e:
            logger.debug(f"Geocoding failed for {city}, {country}: {e}")
            return None, None
    
    def _parse_source_tag(self, tag: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Parse city/country from source tag."""
        if not tag:
            return None, None
        
        city_match = self._local_tag_pattern.match(tag)
        if city_match:
            city, country = self._normalize_city(city_match.group(1))
            return city, country
        
        country_match = self._country_tag_pattern.match(tag)
        if country_match:
            return None, self._titlecase(country_match.group(1))
        
        return None, None
    
    def _normalize_city(self, city_str: str) -> Tuple[Optional[str], Optional[str]]:
        """Normalize city string that may contain country."""
        if "," in city_str:
            city, country = city_str.split(",", 1)
            return self._titlecase(city.strip()), self._titlecase(country.strip())
        return self._titlecase(city_str.strip()), None
    
    def _titlecase(self, s: str) -> str:
        return " ".join(p.capitalize() for p in s.split())
    
    def _map_country_to_region(self, country: str) -> Optional[str]:
        """Map country to geographic region."""
        # This is a simplified version; use a proper mapping in production
        region_map = {
            "Europe": ["France", "Germany", "Italy", "Spain", "United Kingdom"],
            "Asia": ["China", "Japan", "India", "Thailand", "Indonesia"],
            "North America": ["United States", "Canada", "Mexico"],
            # Add more mappings...
        }
        
        for region, countries in region_map.items():
            if country in countries:
                return region
        return None
    
    def _build_prompt(self, batch: List[Tuple[Dict, str, str, asyncio.Future]]) -> str:
        """Build prompt for Moonshot API."""
        prompt = """Extract location (city, country, region) for each news item.
Return JSON array of objects with: city, country, region, confidence, alert_uuid.

--- ENTRIES ---\n\n"""
        
        for idx, (entry, source_tag, uuid, _) in enumerate(batch):
            prompt += f"Item {idx}: {entry['title'][:120]} | Tag: {source_tag} | UUID: {uuid}\n"
        
        return prompt
    
    def _parse_response(self, response: str, batch: List[Tuple[Dict, str, str, asyncio.Future]]) -> Dict[str, Dict]:
        """Parse Moonshot response and return results dict."""
        import re, json
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if not match:
            raise ValueError("No JSON array found in Moonshot response")
        
        results = json.loads(match.group())
        return {item["alert_uuid"]: item for item in results}

# Global extractor instance
LOCATION_EXTRACTOR = LocationExtractor()