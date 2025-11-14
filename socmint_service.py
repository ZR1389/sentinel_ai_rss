import os
from apify_client import ApifyClient
import logging
import json
from psycopg2.extras import Json
from db_utils import execute
from db_utils import fetch_one

logger = logging.getLogger(__name__)

# Cache metrics tracking
_cache_metrics = {
    'hits': 0,
    'misses': 0,
    'total_requests': 0,
    'apify_calls': 0,
    'cache_saves': 0,
    'errors': 0
}

def get_cache_metrics():
    """Return current cache performance metrics."""
    total = _cache_metrics['total_requests']
    if total > 0:
        hit_rate = (_cache_metrics['hits'] / total) * 100
        return {
            **_cache_metrics,
            'hit_rate_percent': round(hit_rate, 2)
        }
    return {**_cache_metrics, 'hit_rate_percent': 0.0}

def reset_cache_metrics():
    """Reset cache metrics counters."""
    global _cache_metrics
    _cache_metrics = {
        'hits': 0,
        'misses': 0,
        'total_requests': 0,
        'apify_calls': 0,
        'cache_saves': 0,
        'errors': 0
    }
    logger.info("[SOCMINT] Cache metrics reset")

def log_cache_performance_summary():
    """Log a comprehensive SOCMINT cache performance summary."""
    metrics = get_cache_metrics()
    
    if metrics['total_requests'] == 0:
        logger.info("[SOCMINT] No cache activity to report")
        return
    
    logger.info("=" * 60)
    logger.info("📊 SOCMINT CACHE PERFORMANCE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total Cache Requests: {metrics['total_requests']:,}")
    logger.info(f"Cache Hits: {metrics['hits']:,}")
    logger.info(f"Cache Misses: {metrics['misses']:,}")
    logger.info(f"Hit Rate: {metrics['hit_rate_percent']:.1f}%")
    logger.info(f"Fresh Apify Calls: {metrics['apify_calls']:,}")
    logger.info(f"New Cache Saves: {metrics['cache_saves']:,}")
    logger.info(f"Errors: {metrics['errors']:,}")
    
    # Calculate efficiency
    if metrics['apify_calls'] > 0:
        cache_efficiency = ((metrics['total_requests'] - metrics['apify_calls']) / metrics['total_requests']) * 100
        logger.info(f"Cache Efficiency: {cache_efficiency:.1f}% (avoided {metrics['hits']} Apify calls)")
    
    logger.info("=" * 60)

class SocmintService:
    def __init__(self):
        token = os.getenv('APIFY_API_TOKEN')
        if not token:
            logger.warning("APIFY_API_TOKEN not set")
        self.client = ApifyClient(token=token)

    def run_instagram_scraper(self, username: str, results_limit: int = 20) -> dict:
        """Scrape Instagram profile and posts for threat intel"""
        actor_id = "apify/instagram-scraper"
        
        run_input = {
            "usernames": [username],
            "resultsLimit": results_limit,
            "searchType": "user"  # Explicitly set to user profile mode
        }
        
        try:
            logger.info(f"[SOCMINT] Starting Instagram scrape: {username} (limit={results_limit})")
            _cache_metrics['apify_calls'] += 1
            
            run = self.client.actor(actor_id).call(run_input=run_input)
            items = [i for i in self.client.dataset(run["defaultDatasetId"]).iterate_items()]
            
            if not items:
                logger.warning(f"[SOCMINT] Instagram scrape returned no data: {username}")
                _cache_metrics['errors'] += 1
                return {"success": False, "error": "No data returned"}
                
            # Extract profile and posts
            profile = next((item for item in items if item.get("type") == "profile"), items[0])
            posts = [item for item in items if item.get("type") == "post"]
            
            logger.info(f"[SOCMINT] Instagram scrape successful: {username} - "
                       f"profile={bool(profile)}, posts={len(posts)}")
            
            return {
                "success": True,
                "data": {
                    "profile": profile,
                    "posts": posts
                }
            }
        except Exception as e:
            logger.error(f"[SOCMINT] Instagram scraper failed: {username} - {str(e)}", exc_info=True)
            _cache_metrics['errors'] += 1
            return {"success": False, "error": str(e)}

    def run_facebook_scraper(self, page_url: str, results_limit: int = 20) -> dict:
        """Scrape Facebook page/group posts for intelligence gathering"""
        actor_id = "apify/facebook-posts-scraper"
        
        # Validate URL format
        if not page_url.startswith(("https://www.facebook.com/", "https://facebook.com/")):
            logger.warning(f"[SOCMINT] Invalid Facebook URL format: {page_url}")
            _cache_metrics['errors'] += 1
            return {"success": False, "error": "Invalid Facebook URL format"}
        
        run_input = {
            "startUrls": [{"url": page_url}],
            "resultsLimit": results_limit,
            "proxyConfig": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]  # Bypass blocks
            }
        }
        
        try:
            logger.info(f"[SOCMINT] Starting Facebook scrape: {page_url} (limit={results_limit})")
            _cache_metrics['apify_calls'] += 1
            
            run = self.client.actor(actor_id).call(run_input=run_input)
            items = [i for i in self.client.dataset(run["defaultDatasetId"]).iterate_items()]
            
            if not items:
                logger.warning(f"[SOCMINT] Facebook scrape returned no data: {page_url}")
                _cache_metrics['errors'] += 1
                return {"success": False, "error": "No data returned or page is private"}
            
            logger.info(f"[SOCMINT] Facebook scrape successful: {page_url} - posts={len(items)}")
            
            return {
                "success": True,
                "data": {
                    "page_info": {
                        "url": page_url,
                        "total_posts": len(items)
                    },
                    "posts": items
                }
            }
        except Exception as e:
            logger.error(f"[SOCMINT] Facebook scraper failed: {page_url} - {str(e)}", exc_info=True)
            _cache_metrics['errors'] += 1
            return {"success": False, "error": str(e)}

    def save_socmint_data(self, platform: str, identifier: str, data: dict) -> bool:
        """Persist SOCMINT data into socmint_profiles via UPSERT."""
        try:
            profile_data = None
            posts_data = None
            if isinstance(data, dict):
                # Normalize into profile_data and posts_data
                profile_data = data.get("profile") or data.get("page_info")
                posts_data = data.get("posts")
            query = (
                "INSERT INTO socmint_profiles (platform, identifier, profile_data, posts_data, scraped_timestamp, analysis_status) "
                "VALUES (%s, %s, %s, %s, NOW(), 'pending') "
                "ON CONFLICT (platform, identifier) DO UPDATE SET "
                "profile_data = EXCLUDED.profile_data, "
                "posts_data = EXCLUDED.posts_data, "
                "scraped_timestamp = EXCLUDED.scraped_timestamp, "
                "analysis_status = 'pending'"
            )
            execute(query, (
                platform,
                identifier,
                Json(profile_data) if profile_data is not None else None,
                Json(posts_data) if posts_data is not None else None,
            ))
            _cache_metrics['cache_saves'] += 1
            logger.info("[SOCMINT] Persisted %s for %s (profile=%s, posts=%s)", 
                       platform, identifier, 
                       bool(profile_data), 
                       len(posts_data) if posts_data else 0)
            return True
        except Exception as e:
            logger.error("[SOCMINT] Failed to persist %s for %s: %s", platform, identifier, e, exc_info=True)
            _cache_metrics['errors'] += 1
            return False

    def get_cached_socmint_data(self, platform: str, identifier: str, ttl_minutes: int = 120) -> dict:
        """Return cached SOCMINT data from DB if within TTL.
        
        Args:
            platform: 'instagram' or 'facebook'
            identifier: username or page id/url segment
            ttl_minutes: cache validity window in minutes
        
        Returns:
            dict: { 'success': bool, 'data': {...}, 'scraped_at': iso_ts } if cached
        """
        _cache_metrics['total_requests'] += 1
        
        try:
            row = fetch_one(
                (
                    "SELECT profile_data, posts_data, scraped_timestamp "
                    "FROM socmint_profiles "
                    "WHERE platform = %s AND identifier = %s "
                    "AND scraped_timestamp > NOW() - (%s || ' minutes')::interval"
                ),
                (platform, identifier, str(int(ttl_minutes)))
            )
            if not row:
                _cache_metrics['misses'] += 1
                logger.debug(f"[SOCMINT] Cache miss: {platform}/{identifier} (TTL={ttl_minutes}m)")
                return {"success": False, "error": "no-cache"}
            
            profile_data = row[0] if isinstance(row, tuple) else row.get("profile_data")
            posts_data = row[1] if isinstance(row, tuple) else row.get("posts_data")
            scraped_ts = row[2] if isinstance(row, tuple) else row.get("scraped_timestamp")
            
            _cache_metrics['hits'] += 1
            logger.info(f"[SOCMINT] Cache hit: {platform}/{identifier} - "
                       f"age={self._format_cache_age(scraped_ts)}, "
                       f"posts={len(posts_data) if posts_data else 0}")
            
            data = {}
            if platform == 'facebook':
                data["page_info"] = profile_data
            else:
                data["profile"] = profile_data
            data["posts"] = posts_data or []
            return {"success": True, "data": data, "scraped_at": scraped_ts.isoformat() if scraped_ts else None}
        except Exception as e:
            logger.warning(f"[SOCMINT] Cache lookup failed: {platform}/{identifier} - {e}")
            _cache_metrics['errors'] += 1
            return {"success": False, "error": str(e)}
    
    def _format_cache_age(self, scraped_ts):
        """Format cache age in human-readable format."""
        try:
            from datetime import datetime
            if scraped_ts:
                age = datetime.utcnow() - scraped_ts
                if age.days > 0:
                    return f"{age.days}d"
                elif age.seconds > 3600:
                    return f"{age.seconds // 3600}h"
                else:
                    return f"{age.seconds // 60}m"
        except Exception:
            pass
        return "unknown"
