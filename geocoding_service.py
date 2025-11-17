"""geocoding_service.py

Geocode location strings with Redis + PostgreSQL caching + Nominatim + OpenCage.
Multi-tier: Redis -> Postgres -> Nominatim (free) -> OpenCage (quota 2,500/day).
"""

import os
import logging
import hashlib
import json
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import requests

logger = logging.getLogger("geocoding")

OPENCAGE_API_KEY = os.getenv("OPENCAGE_API_KEY")
OPENCAGE_URL = "https://api.opencagedata.com/geocode/v1/json"

# Nominatim configuration (respect usage policy)
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
NOMINATIM_EMAIL = os.getenv("NOMINATIM_EMAIL", "")
USER_AGENT_APP = os.getenv("USER_AGENT_APP", "sentinel-ai-geocoding/1.0")
_nominatim_last_call = datetime.utcnow() - timedelta(seconds=2)
_nominatim_min_interval = float(os.getenv("NOMINATIM_MIN_INTERVAL_SEC", "1.0"))
NOMINATIM_ENABLED = os.getenv("NOMINATIM_ENABLED", "true").lower() in ("1","true","yes","on")

# Daily quota tracking
_daily_requests = 0
_daily_limit = 2500
_last_reset = datetime.utcnow().date()


def _get_db_helpers():
    """Get database connection helper"""
    try:
        from db_utils import _get_db_connection
        return _get_db_connection
    except Exception as e:
        logger.error("[geocoding] DB helpers unavailable: %s", e)
        return None


def _get_redis():
    """Get Redis connection if available"""
    try:
        import redis
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return None
        r = redis.from_url(redis_url, decode_responses=True)
        r.ping()
        return r
    except Exception as e:
        logger.debug("[geocoding] Redis unavailable: %s", e)
        return None


def _normalize_location(location: str) -> str:
    """Clean up location string for consistent caching"""
    if not location:
        return ""
    # Remove extra whitespace, lowercase, strip
    normalized = " ".join(location.strip().lower().split())
    return normalized


def _cache_key(location: str) -> str:
    """Generate Redis cache key"""
    normalized = _normalize_location(location)
    hash_part = hashlib.md5(normalized.encode()).hexdigest()[:12]
    return f"geocode:{hash_part}"


def _check_redis_cache(location: str) -> Optional[Dict]:
    """Check Redis for cached geocoding result"""
    redis_client = _get_redis()
    if not redis_client:
        return None
    
    try:
        key = _cache_key(location)
        cached = redis_client.get(key)
        if cached:
            logger.info(f"[geocoding] Redis HIT: {location}")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"[geocoding] Redis read error: {e}")
    
    return None


def _set_redis_cache(location: str, data: Dict, ttl: int = 86400 * 30):
    """Store geocoding result in Redis (30 day TTL)"""
    redis_client = _get_redis()
    if not redis_client:
        return
    
    try:
        key = _cache_key(location)
        redis_client.setex(key, ttl, json.dumps(data))
        logger.debug(f"[geocoding] Redis SAVE: {location}")
    except Exception as e:
        logger.warning(f"[geocoding] Redis write error: {e}")


def _check_db_cache(location: str) -> Optional[Dict]:
    """Check PostgreSQL for cached geocoding result"""
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return None
    
    normalized = _normalize_location(location)
    
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE geocoded_locations 
                SET last_used_at = now() 
                WHERE normalized_text = %s 
                RETURNING latitude, longitude, country_code, confidence, admin_level_1, admin_level_2
                """,
                (normalized,)
            )
            row = cur.fetchone()
            
            if row:
                logger.info(f"[geocoding] DB HIT: {location}")
                return {
                    'lat': float(row[0]),
                    'lon': float(row[1]),
                    'country_code': row[2],
                    'confidence': row[3],
                    'admin_level_1': row[4],
                    'admin_level_2': row[5],
                    'source': 'db_cache'
                }
    except Exception as e:
        logger.warning(f"[geocoding] DB read error: {e}")
    
    return None


def _save_to_db(location: str, data: Dict):
    """Persist geocoding result to PostgreSQL"""
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return
    
    normalized = _normalize_location(location)
    
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO geocoded_locations(
                    location_text, normalized_text, latitude, longitude, 
                    country_code, admin_level_1, admin_level_2, confidence
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (location_text) 
                DO UPDATE SET 
                    last_used_at = now(),
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    confidence = EXCLUDED.confidence
                """,
                (
                    location, normalized, data['lat'], data['lon'],
                    data.get('country_code'), data.get('admin_level_1'), 
                    data.get('admin_level_2'), data.get('confidence', 5)
                )
            )
            logger.debug(f"[geocoding] DB SAVE: {location}")
    except Exception as e:
        logger.error(f"[geocoding] DB save error: {e}")


def _call_nominatim(location: str) -> Optional[Dict]:
        """Call Nominatim (free) with polite rate limiting and headers.
        Returns a geocoding result compatible with OpenCage format used here.
        """
        global _nominatim_last_call
        if not NOMINATIM_ENABLED:
            return None

        # Rate limit to 1 req/sec per policy
        now = datetime.utcnow()
        elapsed = (now - _nominatim_last_call).total_seconds()
        if elapsed < _nominatim_min_interval:
            import time
            time.sleep(_nominatim_min_interval - elapsed)

        headers = {
            "User-Agent": USER_AGENT_APP,
            "Accept": "application/json"
        }
        params = {
            "q": location,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 1,
        }
        if NOMINATIM_EMAIL:
            params["email"] = NOMINATIM_EMAIL

        try:
            resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            _nominatim_last_call = datetime.utcnow()
            data = resp.json()
            if isinstance(data, list) and data:
                item = data[0]
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
                addr = item.get("address", {})
                # Map Nominatim 'importance' (0-1+) to 1-10 confidence scale
                try:
                    importance = float(item.get("importance", 0.5))
                except (TypeError, ValueError):
                    importance = 0.5
                confidence = max(1, min(10, int(round(importance * 10))))
                geocoded = {
                    "lat": lat,
                    "lon": lon,
                    "country_code": (addr.get("country_code") or "").upper(),
                    "admin_level_1": addr.get("state") or addr.get("province"),
                    "admin_level_2": addr.get("city") or addr.get("town") or addr.get("county"),
                    "confidence": confidence,
                    "source": "nominatim",
                    "formatted": item.get("display_name")
                }
                logger.info(f"[geocoding] Nominatim: {location}")
                return geocoded
            else:
                logger.debug(f"[geocoding] Nominatim no results: {location}")
                return None
        except Exception as e:
            logger.warning(f"[geocoding] Nominatim error: {e}")
            return None


def _call_opencage(location: str) -> Optional[Dict]:
    """Call OpenCage API (counts toward daily quota)"""
    global _daily_requests, _last_reset
    
    if not OPENCAGE_API_KEY:
        logger.error("[geocoding] OPENCAGE_API_KEY not set")
        return None
    
    # Reset daily counter if new day
    today = datetime.utcnow().date()
    if today > _last_reset:
        _daily_requests = 0
        _last_reset = today
    
    # Check quota
    if _daily_requests >= _daily_limit:
        logger.warning(f"[geocoding] Daily quota exceeded ({_daily_limit})")
        return None
    
    try:
        params = {
            'q': location,
            'key': OPENCAGE_API_KEY,
            'limit': 1,
            'no_annotations': 1
        }
        
        response = requests.get(OPENCAGE_URL, params=params, timeout=10)
        response.raise_for_status()
        
        _daily_requests += 1
        
        data = response.json()
        
        if data.get('results'):
            result = data['results'][0]
            geo = result['geometry']
            components = result.get('components', {})
            
            geocoded = {
                'lat': geo['lat'],
                'lon': geo['lng'],
                'country_code': components.get('country_code', '').upper(),
                'admin_level_1': components.get('state') or components.get('province'),
                'admin_level_2': components.get('city') or components.get('town'),
                'confidence': result.get('confidence', 5),
                'source': 'opencage',
                'formatted': result.get('formatted')
            }
            
            logger.info(f"[geocoding] OpenCage API ({_daily_requests}/{_daily_limit}): {location}")
            return geocoded
        else:
            logger.warning(f"[geocoding] No results from OpenCage: {location}")
            return None
            
    except Exception as e:
        logger.error(f"[geocoding] OpenCage API error: {e}")
        return None


def geocode(location: str, force_api: bool = False) -> Optional[Dict]:
    """
    Geocode a location string with multi-tier caching.
    
    Cache hierarchy:
    1. Redis (fastest, ~1ms)
    2. PostgreSQL (persistent, ~5ms)
    3. OpenCage API (quota-limited, ~200ms)
    
    Args:
        location: Location string (e.g., "Paris, France")
        force_api: Skip cache and force API call
    
    Returns:
        {
            'lat': float,
            'lon': float,
            'country_code': str,
            'confidence': int,
            'source': str
        }
    """
    
    if not location or not location.strip():
        return None
    
    location = location.strip()
    
    # 1. Check Redis cache
    if not force_api:
        cached = _check_redis_cache(location)
        if cached:
            return cached
        
        # 2. Check PostgreSQL cache
        cached = _check_db_cache(location)
        if cached:
            # Backfill Redis for faster future lookups
            _set_redis_cache(location, cached)
            return cached
    
    # 3. Try Nominatim (free tier)
    result = _call_nominatim(location)
    if not result:
        # 4. Fallback to OpenCage (quota-limited)
        result = _call_opencage(location)
    
    if result:
        # Cache in both Redis and PostgreSQL
        _set_redis_cache(location, result)
        _save_to_db(location, result)
    
    return result


def batch_geocode(locations: List[str], max_api_calls: int = 100) -> Dict[str, Dict]:
    """
    Geocode multiple locations efficiently.
    Only calls API for cache misses, respects max_api_calls limit.
    
    Args:
        locations: List of location strings
        max_api_calls: Maximum API calls to make (default 100)
    
    Returns:
        {
            'location1': {'lat': ..., 'lon': ...},
            'location2': {'lat': ..., 'lon': ...},
            ...
        }
    """
    results = {}
    api_calls_used = 0
    
    # Deduplicate by normalized text to avoid repeat calls
    seen = {}
    for location in locations:
        if not location:
            continue
        norm = _normalize_location(location)
        if norm in seen:
            # Reuse prior result if any
            if seen[norm] is not None:
                results[location] = seen[norm]
            continue

        # Try cache first
        result = geocode(location, force_api=False)
        
        if result:
            results[location] = result
            seen[norm] = result
        elif api_calls_used < max_api_calls:
            # Cache miss, try API
            result = geocode(location, force_api=True)
            if result:
                results[location] = result
                api_calls_used += 1
            seen[norm] = result
        else:
            seen[norm] = None
    
    logger.info(f"[geocoding] Batch: {len(results)}/{len(locations)} geocoded, {api_calls_used} API calls")
    return results


def get_quota_status() -> Dict:
    """Return current OpenCage API quota usage"""
    return {
        'requests_today': _daily_requests,
        'daily_limit': _daily_limit,
        'remaining': _daily_limit - _daily_requests,
        'reset_date': _last_reset.isoformat()
    }


def geocode_and_update_table(table_name: str, id_column: str, location_column: str, 
                             lat_column: str = 'latitude', lon_column: str = 'longitude',
                             limit: int = 100):
    """
    Geocode rows in a table that are missing coordinates.
    
    Args:
        table_name: Table to update
        id_column: Primary key column
        location_column: Column containing location text
        lat_column: Column to store latitude
        lon_column: Column to store longitude
        limit: Max rows to process in one run
    """
    get_conn_cm = _get_db_helpers()
    if not get_conn_cm:
        return
    
    try:
        with get_conn_cm() as conn:
            cur = conn.cursor()
            
            # Find rows without coordinates
            query = f"""
                SELECT {id_column}, {location_column}
                FROM {table_name}
                WHERE {lat_column} IS NULL 
                  AND {location_column} IS NOT NULL
                  AND {location_column} != ''
                LIMIT %s
            """
            cur.execute(query, (limit,))
            rows = cur.fetchall()
            
            geocoded_count = 0
            
            for row_id, location in rows:
                result = geocode(location)
                
                if result:
                    update_query = f"""
                        UPDATE {table_name}
                        SET {lat_column} = %s, {lon_column} = %s
                        WHERE {id_column} = %s
                    """
                    cur.execute(update_query, (result['lat'], result['lon'], row_id))
                    geocoded_count += 1
            
            conn.commit()
            logger.info(f"[geocoding] Updated {geocoded_count} rows in {table_name}")
            
    except Exception as e:
        logger.error(f"[geocoding] Table update failed: {e}")
