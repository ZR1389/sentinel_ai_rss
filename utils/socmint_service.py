import os
from apify_client import ApifyClient
import logging
import json
from datetime import datetime
from collections import deque
from psycopg2.extras import Json
from utils.db_utils import execute
from utils.db_utils import fetch_one

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

# Daily quota tracking
_daily_usage = {'instagram': 0, 'facebook': 0, 'last_reset': datetime.utcnow().date()}

def check_daily_quota(platform: str) -> bool:
    """Check if daily Apify quota allows another call."""
    global _daily_usage
    
    # Reset counters at midnight UTC
    today = datetime.utcnow().date()
    if today > _daily_usage['last_reset']:
        _daily_usage = {'instagram': 0, 'facebook': 0, 'last_reset': today}
        logger.info(f"[SOCMINT] Daily quota counters reset for {today}")
    
    limits = {
        'instagram': int(os.getenv('SOCMINT_INSTAGRAM_DAILY_APIFY_LIMIT', 200)),
        'facebook': int(os.getenv('SOCMINT_FACEBOOK_DAILY_APIFY_LIMIT', 100))
    }
    
    current = _daily_usage.get(platform, 0)
    limit = limits.get(platform, 999)
    
    if current >= limit:
        logger.warning(f"[SOCMINT] Daily quota exceeded for {platform}: {current}/{limit}")
        return False
    
    return True

def increment_daily_usage(platform: str):
    """Increment daily usage counter for platform."""
    global _daily_usage
    _daily_usage[platform] = _daily_usage.get(platform, 0) + 1
    logger.debug(f"[SOCMINT] Daily usage for {platform}: {_daily_usage[platform]}")

def get_daily_usage_stats() -> dict:
    """Get current daily usage statistics."""
    limits = {
        'instagram': int(os.getenv('SOCMINT_INSTAGRAM_DAILY_APIFY_LIMIT', 200)),
        'facebook': int(os.getenv('SOCMINT_FACEBOOK_DAILY_APIFY_LIMIT', 100))
    }
    
    return {
        'instagram': {
            'used': _daily_usage.get('instagram', 0),
            'limit': limits['instagram'],
            'remaining': limits['instagram'] - _daily_usage.get('instagram', 0)
        },
        'facebook': {
            'used': _daily_usage.get('facebook', 0),
            'limit': limits['facebook'],
            'remaining': limits['facebook'] - _daily_usage.get('facebook', 0)
        },
        'last_reset': _daily_usage['last_reset'].isoformat()
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
        # Per-platform metrics
        self.platform_metrics = {
            'instagram': {
                'cache_hits': 0,
                'cache_misses': 0,
                'apify_calls': 0,
                'errors': 0
            },
            'facebook': {
                'cache_hits': 0,
                'cache_misses': 0,
                'apify_calls': 0,
                'errors': 0
            }
        }
        self.error_buffer = deque(maxlen=100)

    def run_instagram_scraper(self, username: str, results_limit: int = 20) -> dict:
        """Scrape Instagram profile and posts for threat intel with cache-first pattern."""
        
        # 1. Try cache first (2-hour TTL)
        ttl_minutes = int(os.getenv('SOCMINT_CACHE_TTL_MINUTES', 120))
        cached = self.get_cached_socmint_data('instagram', username, ttl_minutes)
        
        if cached.get('success'):
            logger.info(f"[SOCMINT] Cache hit for Instagram/{username}")
            return {
                "success": True,
                "data": cached['data'],
                "source": "cache",
                "scraped_at": cached.get('scraped_at')
            }
        
        # 2. Cache miss - log and check quota
        logger.info(f"[SOCMINT] Cache miss for Instagram/{username}, checking quota")
        
        if not check_daily_quota('instagram'):
            logger.warning(f"[SOCMINT] Instagram quota exceeded, cannot scrape {username}")
            _cache_metrics['errors'] += 1
            return {
                "success": False,
                "error": "Daily quota exceeded - Instagram SOCMINT temporarily disabled"
            }
        
        # 3. Quota available - proceed with fresh scrape
        actor_id = "apify/instagram-scraper"
        
        run_input = {
            "usernames": [username],
            "resultsLimit": results_limit,
            "searchType": "user"
        }
        
        try:
            logger.info(f"[SOCMINT] Starting fresh Instagram scrape: {username} (limit={results_limit})")
            _cache_metrics['apify_calls'] += 1
            self.platform_metrics['instagram']['apify_calls'] += 1
            increment_daily_usage('instagram')
            
            run = self.client.actor(actor_id).call(run_input=run_input)
            items = [i for i in self.client.dataset(run["defaultDatasetId"]).iterate_items()]
            
            if not items:
                logger.warning(f"[SOCMINT] Instagram scrape returned no data: {username}")
                _cache_metrics['errors'] += 1
                self.platform_metrics['instagram']['errors'] += 1
                self.error_buffer.append({
                    'ts': datetime.utcnow().isoformat(),
                    'platform': 'instagram',
                    'identifier': username,
                    'error': 'empty-result'
                })
                return {"success": False, "error": "No data returned"}
                
            # Extract profile and posts
            profile = next((item for item in items if item.get("type") == "profile"), items[0])
            posts = [item for item in items if item.get("type") == "post"]
            
            logger.info(f"[SOCMINT] Instagram scrape successful: {username} - "
                       f"profile={bool(profile)}, posts={len(posts)}")
            
            result_data = {
                "profile": profile,
                "posts": posts
            }
            
            # 4. Save to cache for future requests
            self.save_socmint_data('instagram', username, result_data)
            
            return {
                "success": True,
                "data": result_data,
                "source": "fresh"
            }
        except Exception as e:
            logger.error(f"[SOCMINT] Instagram scraper failed: {username} - {str(e)}", exc_info=True)
            _cache_metrics['errors'] += 1
            self.platform_metrics['instagram']['errors'] += 1
            self.error_buffer.append({
                'ts': datetime.utcnow().isoformat(),
                'platform': 'instagram',
                'identifier': username,
                'error': str(e)
            })
            return {"success": False, "error": str(e)}

    def run_facebook_scraper(self, page_url: str, results_limit: int = 20) -> dict:
        """Scrape Facebook page/group posts with cache-first pattern."""
        
        # Validate URL format early
        if not page_url.startswith(("https://www.facebook.com/", "https://facebook.com/")):
            logger.warning(f"[SOCMINT] Invalid Facebook URL format: {page_url}")
            _cache_metrics['errors'] += 1
            return {"success": False, "error": "Invalid Facebook URL format"}
        
        # Extract identifier from URL for cache key
        identifier = page_url.replace("https://www.facebook.com/", "").replace("https://facebook.com/", "").split("?")[0]
        
        # 1. Try cache first (2-hour TTL)
        ttl_minutes = int(os.getenv('SOCMINT_CACHE_TTL_MINUTES', 120))
        cached = self.get_cached_socmint_data('facebook', identifier, ttl_minutes)
        
        if cached.get('success'):
            logger.info(f"[SOCMINT] Cache hit for Facebook/{identifier}")
            return {
                "success": True,
                "data": cached['data'],
                "source": "cache",
                "scraped_at": cached.get('scraped_at')
            }
        
        # 2. Cache miss - log and check quota
        logger.info(f"[SOCMINT] Cache miss for Facebook/{identifier}, checking quota")
        
        if not check_daily_quota('facebook'):
            logger.warning(f"[SOCMINT] Facebook quota exceeded, cannot scrape {page_url}")
            _cache_metrics['errors'] += 1
            return {
                "success": False,
                "error": "Daily quota exceeded - Facebook SOCMINT temporarily disabled"
            }
        
        # 3. Quota available - proceed with fresh scrape
        actor_id = "apify/facebook-posts-scraper"
        
        run_input = {
            "startUrls": [{"url": page_url}],
            "resultsLimit": results_limit,
            "proxyConfig": {
                "useApifyProxy": True,
                "apifyProxyGroups": ["RESIDENTIAL"]
            }
        }
        
        try:
            logger.info(f"[SOCMINT] Starting fresh Facebook scrape: {page_url} (limit={results_limit})")
            _cache_metrics['apify_calls'] += 1
            self.platform_metrics['facebook']['apify_calls'] += 1
            increment_daily_usage('facebook')
            
            run = self.client.actor(actor_id).call(run_input=run_input)
            items = [i for i in self.client.dataset(run["defaultDatasetId"]).iterate_items()]
            
            if not items:
                logger.warning(f"[SOCMINT] Facebook scrape returned no data: {page_url}")
                _cache_metrics['errors'] += 1
                self.platform_metrics['facebook']['errors'] += 1
                self.error_buffer.append({
                    'ts': datetime.utcnow().isoformat(),
                    'platform': 'facebook',
                    'identifier': identifier,
                    'error': 'empty-result'
                })
                return {"success": False, "error": "No data returned or page is private"}
            
            logger.info(f"[SOCMINT] Facebook scrape successful: {page_url} - posts={len(items)}")
            
            result_data = {
                "page_info": {
                    "url": page_url,
                    "total_posts": len(items)
                },
                "posts": items
            }
            
            # 4. Save to cache for future requests
            self.save_socmint_data('facebook', identifier, result_data)
            
            return {
                "success": True,
                "data": result_data,
                "source": "fresh"
            }
        except Exception as e:
            logger.error(f"[SOCMINT] Facebook scraper failed: {page_url} - {str(e)}", exc_info=True)
            _cache_metrics['errors'] += 1
            self.platform_metrics['facebook']['errors'] += 1
            self.error_buffer.append({
                'ts': datetime.utcnow().isoformat(),
                'platform': 'facebook',
                'identifier': identifier,
                'error': str(e)
            })
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
                if platform in self.platform_metrics:
                    self.platform_metrics[platform]['cache_misses'] += 1
                logger.debug(f"[SOCMINT] Cache miss: {platform}/{identifier} (TTL={ttl_minutes}m)")
                return {"success": False, "error": "no-cache"}
            
            profile_data = row[0] if isinstance(row, tuple) else row.get("profile_data")
            posts_data = row[1] if isinstance(row, tuple) else row.get("posts_data")
            scraped_ts = row[2] if isinstance(row, tuple) else row.get("scraped_timestamp")
            
            _cache_metrics['hits'] += 1
            if platform in self.platform_metrics:
                self.platform_metrics[platform]['cache_hits'] += 1
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
            if platform in self.platform_metrics:
                self.platform_metrics[platform]['errors'] += 1
            self.error_buffer.append({
                'ts': datetime.utcnow().isoformat(),
                'platform': platform,
                'identifier': identifier,
                'error': str(e)
            })
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

    def generate_insights(self, ig: dict, fb: dict) -> dict:
        """Generate structured insights and recommendations.

        Args:
            ig: Instagram stats dict.
            fb: Facebook stats dict.
        Returns:
            Dict with cache_ttl_optimal, apify_limit_risk, recommendations list.
        """
        insights = {}

        # Insight 1: Are current TTL settings yielding good hit rate?
        insights["cache_ttl_optimal"] = ig.get("hit_rate", 0) > 0.65 and fb.get("hit_rate", 0) > 0.60

        # Insight 2: Apify daily limit risk assessment (simple thresholding)
        apify_today = ig.get("apify_calls", 0) + fb.get("apify_calls", 0)
        if apify_today < 100:
            risk = "low"
        elif apify_today < 200:
            risk = "medium"
        else:
            risk = "high"
        insights["apify_limit_risk"] = risk

        # Recommendations bucket
        insights["recommendations"] = []

        if ig.get("hit_rate", 0) < 0.60:
            insights["recommendations"].append("Increase Instagram TTL by +1 hour")

        if fb.get("apify_calls", 0) > 30:
            insights["recommendations"].append("Reduce Facebook maxPosts from 10 to 5")

        if ig.get("error_rate", 0) > 0.05:
            insights["recommendations"].append("Check Instagram actor stability")

        return insights

    def get_dashboard_metrics(self):
        def calc(platform: str):
            p = self.platform_metrics[platform]
            hits = p['cache_hits']
            misses = p['cache_misses']
            calls = p['apify_calls']
            errors = p['errors']
            total = hits + misses if (hits + misses) > 0 else 1
            hit_rate = hits / total
            error_rate = errors / (calls if calls > 0 else 1)
            cost_per_call = 0.20 if platform == 'instagram' else 0.30
            estimated_savings = hits * cost_per_call
            return {
                'cache_hits': hits,
                'cache_misses': misses,
                'apify_calls': calls,
                'errors': errors,
                'hit_rate': hit_rate,
                'error_rate': error_rate,
                'estimated_savings_usd': round(estimated_savings, 2)
            }
        ig_stats = calc('instagram')
        fb_stats = calc('facebook')
        totals = {
            'cache_hits': ig_stats['cache_hits'] + fb_stats['cache_hits'],
            'cache_misses': ig_stats['cache_misses'] + fb_stats['cache_misses'],
            'apify_calls': ig_stats['apify_calls'] + fb_stats['apify_calls'],
            'errors': ig_stats['errors'] + fb_stats['errors']
        }
        denom = (totals['cache_hits'] + totals['cache_misses']) or 1
        totals['overall_hit_rate'] = totals['cache_hits'] / denom
        totals['overall_error_rate'] = totals['errors'] / (totals['apify_calls'] or 1)
        totals['estimated_total_savings_usd'] = round(ig_stats['estimated_savings_usd'] + fb_stats['estimated_savings_usd'], 2)
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'platforms': {
                'instagram': ig_stats,
                'facebook': fb_stats
            },
            'totals': totals,
            'daily_usage': get_daily_usage_stats(),
            'recent_errors': list(self.error_buffer)[-20:],
            'insights': self.generate_insights(ig_stats, fb_stats)
        }
