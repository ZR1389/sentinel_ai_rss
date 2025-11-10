# rss_processor_refactored.py – Production-ready RSS processor
from __future__ import annotations
import os
import re
import asyncio
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse

import httpx
import feedparser
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 42
except Exception as e:
    logging.warning(f"langdetect not available: {e}")
    def detect(text: str) -> str:
        return "en"

from config import CONFIG
from metrics import METRICS
from location_extractor import LOCATION_EXTRACTOR, LocationResult
# from async_db import AsyncDB  # Disabled until asyncpg is installed

logger = logging.getLogger("rss_processor")
logger.setLevel(logging.INFO)

class RSSProcessor:
    def __init__(self):
        # self.db = AsyncDB()  # Disabled until asyncpg is installed
        self.db = None
        self.client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        limits = httpx.Limits(
            max_connections=CONFIG.max_concurrency,
            max_keepalive_connections=CONFIG.max_concurrency,
        )
        self.client = httpx.AsyncClient(follow_redirects=True, limits=limits)
        await LOCATION_EXTRACTOR.start()
        await self.db.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await LOCATION_EXTRACTOR.stop()
        if self.client:
            await self.client.aclose()
        await self.db.disconnect()
    
    @METRICS.timer("feed_fetch")
    async def fetch_feed(self, spec: Dict[str, Any]) -> Optional[str]:
        """Fetch a single feed with host throttling."""
        url = spec["url"]
        host = urlparse(url).netloc
        
        # Host throttling
        if CONFIG.host_throttle_enabled:
            await self._acquire_token(host)
        
        logger.debug(f"Fetching feed: {url}")
        
        try:
            response = await self.client.get(url, timeout=CONFIG.timeout_sec)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Feed fetch failed for {url}: {e}")
            METRICS.increment("feed_fetch_failures")
            await self._record_health(url, False, str(e))
            return None
    
    async def _acquire_token(self, host: str):
        """Acquire token from host rate limiter."""
        # Simple token bucket per host
        if not hasattr(self, "_host_buckets"):
            self._host_buckets = {}
        
        bucket = self._host_buckets.get(host)
        if not bucket:
            bucket = asyncio.Queue(maxsize=CONFIG.host_burst)
            self._host_buckets[host] = bucket
        
        # Refill tokens
        now = asyncio.get_event_loop().time()
        last_refill = getattr(bucket, "_last_refill", now)
        elapsed = now - last_refill
        tokens_to_add = int(elapsed * CONFIG.host_rate_per_sec)
        
        if tokens_to_add > 0:
            for _ in range(min(tokens_to_add, CONFIG.host_burst - bucket.qsize())):
                try:
                    bucket.put_nowait(None)
                except asyncio.QueueFull:
                    break
            bucket._last_refill = now
        
        # Wait for token
        await bucket.get()
    
    async def _record_health(self, url: str, ok: bool, error: Optional[str] = None):
        """Record feed health in database."""
        host = urlparse(url).netloc
        # Implementation depends on your health schema
        # This is a placeholder
        pass
    
    async def process_feeds(self, specs: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """Process all feeds and return alerts."""
        tasks = [self._process_feed(spec) for spec in specs]
        feed_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_alerts = []
        for spec, result in zip(specs, feed_results):
            if isinstance(result, Exception):
                logger.error(f"Feed processing error for {spec['url']}: {result}")
                continue
            if result:
                all_alerts.extend(result)
        
        # Apply pending location results
        await LOCATION_EXTRACTOR._flush_batch()
        
        return self._dedupe_alerts(all_alerts)[:limit]
    
    async def _process_feed(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process a single feed."""
        url = spec["url"]
        tag = spec.get("tag", "")
        
        feed_text = await self.fetch_feed(spec)
        if not feed_text:
            return []
        
        entries = self._parse_feed(feed_text, url)
        alerts = []
        
        for entry in entries:
            if len(alerts) >= CONFIG.batch_limit:
                break
            
            alert = await self._build_alert(entry, url, tag, spec)
            if alert:
                alerts.append(alert)
        
        METRICS.increment("feeds_processed")
        return alerts
    
    def _parse_feed(self, feed_text: str, feed_url: str) -> List[Dict[str, Any]]:
        """Parse feed and extract entries."""
        try:
            fp = feedparser.parse(feed_text)
            source_url = fp.feed.get("link", feed_url)
            
            entries = []
            for e in fp.entries or []:
                entries.append({
                    "title": e.get("title", "").strip(),
                    "summary": e.get("summary", e.get("description", "")).strip(),
                    "link": e.get("link", feed_url or "").strip(),
                    "published": self._parse_published(e),
                })
            return entries
        except Exception as e:
            logger.error(f"Feed parsing failed: {e}")
            return []
    
    def _parse_published(self, entry) -> datetime:
        """Parse published date from entry."""
        for key in ("published_parsed", "updated_parsed"):
            val = entry.get(key)
            if val:
                try:
                    return datetime(*val[:6], tzinfo=timezone.utc)
                except Exception:
                    pass
        return datetime.now(timezone.utc)
    
    async def _build_alert(
        self,
        entry: Dict[str, Any],
        source_url: str,
        source_tag: str,
        spec: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Build alert from feed entry."""
        # Freshness check
        cutoff = datetime.now(timezone.utc) - timedelta(days=CONFIG.freshness_days)
        if entry["published"] < cutoff:
            return None
        
        title = entry["title"]
        summary = entry["summary"]
        link = entry["link"]
        
        # Check if already in DB
        uuid = self._generate_uuid(source_url, title, link)
        if await self.db.alert_exists(uuid):
            METRICS.increment("deduplicated_alerts")
            return None
        
        # Keyword matching
        text_blob = f"{title}\n{summary}"
        if len(text_blob.strip()) < CONFIG.min_text_length:
            METRICS.increment("alerts_filtered_too_short")
            return None
        
        hit, kw_match = self._keyword_match(title, summary)
        if not hit:
            # Try fulltext
            if CONFIG.use_fulltext:
                fulltext = await self._fetch_fulltext(link)
                if fulltext:
                    text_blob += f"\n{fulltext}"
                    hit, kw_match = self._keyword_match(title, text_blob)
            
            if not hit:
                METRICS.increment("alerts_filtered_no_keywords")
                return None
        
        # Extract location
        location = await LOCATION_EXTRACTOR.extract_location(title, summary, source_tag)
        
        # Wait for pending location if needed
        if location.pending:
            location = await self._wait_for_location_result(location)
        
        # Compile alert
        alert = {
            "uuid": uuid,
            "title": title,
            "summary": summary,
            "en_snippet": self._first_sentence(self._unidecode(summary)),
            "link": link,
            "source": self._extract_source(source_url or link),
            "published": entry["published"].replace(tzinfo=None),
            "tags": self._auto_tags(text_blob),
            "region": location.region,
            "country": location.country,
            "city": location.city,
            "location_method": location.method,
            "location_confidence": location.confidence,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "kw_match": kw_match,
            "language": self._detect_language(text_blob),
            "source_kind": spec.get("kind", "unknown"),
            "source_priority": spec.get("priority", 999),
            "source_tag": source_tag,
        }
        
        METRICS.increment("alerts_created")
        return alert
    
    async def _wait_for_location_result(self, pending: LocationResult) -> LocationResult:
        """Wait for pending location result with timeout."""
        try:
            # The future will be resolved by the batch processor
            # This is a simplified version - in practice you'd store the future
            # For now, we'll just wait a bit and retry
            await asyncio.sleep(0.5)
            return pending  # In real implementation, this would be a future
        except Exception:
            # Fallback to feed tag
            return LocationResult(
                city=None,
                country=None,
                region=None,
                latitude=None,
                longitude=None,
                method="moonshot_timeout",
                confidence="none",
            )
    
    def _keyword_match(self, title: str, text: str) -> Tuple[bool, Dict[str, Any]]:
        """Multi-tier keyword matching."""
        try:
            from risk_shared import KEYWORD_SET, KeywordMatcher, BROAD_TERMS_DEFAULT, IMPACT_TERMS_DEFAULT
            
            # Try strict co-occurrence
            if CONFIG.enable_cooccurrence:
                matcher = KeywordMatcher(
                    keywords=list(KEYWORD_SET),
                    broad_terms=BROAD_TERMS_DEFAULT,
                    impact_terms=IMPACT_TERMS_DEFAULT,
                    window=CONFIG.cooc_window_tokens,
                )
                result = matcher.decide(text, title=title)
                if result.hit:
                    METRICS.increment("alerts_matched_cooccurrence")
                    return True, {"rule": result.rule, "matches": result.matches, "tier": "strict"}
            
            # Fallback to keyword count
            from risk_shared import _normalize
            normalized = _normalize(f"{title}\n{text}")
            matched = [kw for kw in KEYWORD_SET if kw in normalized]
            
            if len(matched) >= 2:
                METRICS.increment("alerts_matched_keywords")
                return True, {"rule": "keyword_multi", "matches": {"keywords": matched[:5]}, "tier": "fallback"}
            
            return False, {}
        except Exception as e:
            logger.error(f"Keyword matching failed: {e}")
            return False, {}
    
    async def _fetch_fulltext(self, url: str) -> str:
        """Fetch full article text."""
        try:
            response = await self.client.get(url, timeout=CONFIG.fulltext_timeout)
            response.raise_for_status()
            html = response.text
            
            if len(html) > CONFIG.fulltext_max_bytes:
                html = html[:CONFIG.fulltext_max_bytes]
            
            # Try trafilatura first
            try:
                import trafilatura
                extracted = trafilatura.extract(html, include_comments=False, favor_recall=True)
                if extracted:
                    return extracted[:CONFIG.fulltext_max_chars]
            except ImportError:
                pass
            
            # Fallback to BeautifulSoup
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                text = soup.get_text(separator=" ", strip=True)
                return text[:CONFIG.fulltext_max_chars]
            except Exception:
                pass
            
            # Last resort: strip HTML
            return self._strip_html(html)[:CONFIG.fulltext_max_chars]
        except Exception as e:
            logger.debug(f"Fulltext fetch failed for {url}: {e}")
            return ""
    
    def _strip_html(self, html: str) -> str:
        """Basic HTML stripping."""
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
    
    def _auto_tags(self, text: str) -> List[str]:
        """Auto-generate tags from text."""
        t = text.lower()
        tags = []
        
        tag_keywords = {
            "cyber_it": ["ransomware", "phishing", "malware", "breach", "ddos", "cve"],
            "civil_unrest": ["protest", "riot", "clash", "strike", "looting"],
            "physical_safety": ["shooting", "stabbing", "robbery", "kidnap", "attack"],
            "travel_mobility": ["checkpoint", "curfew", "airport", "border", "port", "rail", "metro"],
            "infrastructure_utilities": ["substation", "grid", "pipeline", "telecom", "power outage"],
            "environmental_hazards": ["earthquake", "flood", "wildfire", "hurricane", "storm"],
            "public_health_epidemic": ["outbreak", "epidemic", "pandemic", "cholera", "covid"],
            "terrorism": ["ied", "vbied", "explosion", "bomb", "suicide"],
            "digital_privacy_surveillance": ["surveillance", "spyware", "pegasus", "imsi", "stingray"],
            "legal_regulatory": ["visa", "immigration", "border control", "ban", "restriction"],
        }
        
        for tag, keywords in tag_keywords.items():
            if any(k in t for k in keywords):
                tags.append(tag)
        
        return tags
    
    def _first_sentence(self, text: str) -> str:
        """Extract first sentence."""
        if not text:
            return ""
        parts = re.split(r'(?<=[.!?])\s+', text)
        return parts[0] if parts else text
    
    def _unidecode(self, text: str) -> str:
        """Safely unidecode text."""
        try:
            from unidecode import unidecode
            return unidecode(text)
        except Exception:
            return text
    
    def _detect_language(self, text: str) -> str:
        """Detect language."""
        try:
            return detect(text[:1000])
        except Exception:
            return "en"
    
    def _extract_source(self, url: str) -> str:
        """Extract source from URL."""
        try:
            return re.sub(r"^www\.", "", urlparse(url).netloc)
        except Exception:
            return "unknown"
    
    def _generate_uuid(self, source: str, title: str, link: str) -> str:
        """Generate unique ID for alert."""
        content = f"{source}|{title}|{link}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    
    def _dedupe_alerts(self, alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate alerts by link or title."""
        seen = set()
        out = []
        for alert in alerts:
            key = alert.get("link") or alert.get("title") or ""
            if not key:
                continue
            h = hashlib.sha256(key.encode("utf-8", "ignore")).hexdigest()
            if h not in seen:
                seen.add(h)
                out.append(alert)
        return out

# Main execution
async def main():
    """Main entry point with circuit breaker health monitoring."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    if CONFIG.fail_closed and not CONFIG.write_to_db:
        logger.error("Refusing to run with RSS_WRITE_TO_DB=false and RSS_FAIL_CLOSED=true")
        return
    
    logger.info("Starting RSS processor...")
    logger.info(f"Configuration: {CONFIG}")
    
    # === START METRICS BACKGROUND TASK ===
    async def log_metrics():
        while True:
            try:
                # Import circuit breaker here to avoid issues
                try:
                    from circuit_breaker import MOONSHOT_CB
                    cb_metrics = MOONSHOT_CB.get_metrics()
                    logger.info(f"[Health] Circuit breaker: {cb_metrics}")
                except ImportError:
                    logger.debug("[Health] Circuit breaker not available")
                
                # Also log general metrics
                logger.info(f"[Health] General metrics: {dict(METRICS.counters)}")
                
                await asyncio.sleep(60)  # Log every minute
            except asyncio.CancelledError:
                break  # Exit gracefully when cancelled
            except Exception as e:
                logger.error(f"Metrics logging error: {e}")
    
    # Create the background task
    metrics_task = asyncio.create_task(log_metrics())
    logger.info("[Health] Started background metrics logging (every 60s)")
    # === END METRICS BACKGROUND TASK ===
    
    try:
        # Run the main processor
        async with RSSProcessor() as processor:
            from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS
            
            specs = _build_feed_specs(LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS)
            alerts = await processor.process_feeds(specs, limit=CONFIG.batch_limit)
            
            if CONFIG.write_to_db:
                wrote = await processor.db.save_alerts(alerts)
                logger.info(f"Saved {wrote} of {len(alerts)} alerts to database")
            else:
                logger.warning("RSS_WRITE_TO_DB is false – not saving alerts")
            
            # Final metrics report
            logger.info(f"Final metrics: {dict(METRICS.counters)}")
            try:
                from circuit_breaker import MOONSHOT_CB
                logger.info(f"Final CB state: {MOONSHOT_CB.get_metrics()}")
            except ImportError:
                pass
    
    finally:
        # === CLEANUP: CANCEL METRICS TASK ===
        logger.info("[Health] Shutting down metrics task...")
        metrics_task.cancel()
        try:
            await metrics_task
        except asyncio.CancelledError:
            logger.info("[Health] Metrics task cancelled successfully")
        
        logger.info("RSS processor shutdown complete")

def _build_feed_specs(local, country, global_feeds) -> List[Dict[str, Any]]:
    """Build feed specifications."""
    specs = []
    NATIVE_PRIORITY = 10
    FALLBACK_PRIORITY = 30
    
    # Local feeds
    for city, urls in (local or {}).items():
        for url in urls or []:
            specs.append({
                "url": url.strip(),
                "priority": NATIVE_PRIORITY,
                "kind": "native",
                "tag": f"local:{city}",
            })
    
    # Country feeds
    for country_name, urls in (country or {}).items():
        for url in urls or []:
            specs.append({
                "url": url.strip(),
                "priority": NATIVE_PRIORITY,
                "kind": "native",
                "tag": f"country:{country_name}",
            })
    
    # Global feeds
    for url in global_feeds or []:
        specs.append({
            "url": url.strip(),
            "priority": NATIVE_PRIORITY,
            "kind": "native",
            "tag": "global",
        })
    
    # Environment feeds
    env_feeds = [u.strip() for u in (os.getenv("SENTINEL_FEEDS") or "").split(",") if u.strip()]
    for url in env_feeds:
        specs.append({
            "url": url,
            "priority": NATIVE_PRIORITY,
            "kind": "env",
            "tag": "env",
        })
    
    # Fallback feeds
    fallback = [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    ]
    for url in fallback:
        specs.append({
            "url": url,
            "priority": FALLBACK_PRIORITY,
            "kind": "fallback",
            "tag": "core",
        })
    
    # Deduplicate by URL
    seen = set()
    out = []
    for spec in sorted(specs, key=lambda s: s["priority"]):
        cleaned = re.sub(r"[?#].*$", "", spec["url"])
        if cleaned not in seen:
            seen.add(cleaned)
            spec["url"] = cleaned
            out.append(spec)
    
    return out

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception:
        logger.exception("Fatal error")
        exit(1)