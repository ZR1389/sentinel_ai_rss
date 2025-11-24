# Per-channel in-memory fallback state
_memory_channel_rate_limits: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))  # itinerary_uuid -> channel -> [timestamps]

def _make_channel_rate_limit_key(itinerary_uuid: str, channel: str) -> str:
    """Generate Redis key for per-channel rate limit counter.
    Format: alerts:ratelimit:{itinerary_uuid}:{channel}
    """
    return f"{REDIS_KEY_PREFIX}ratelimit:{itinerary_uuid}:{channel}"

def _cleanup_memory_channel_rate_limits(itinerary_uuid: str, channel: str):
    """Remove timestamps older than 1 hour for in-memory per-channel rate limits."""
    cutoff = datetime.utcnow() - timedelta(hours=1)
    _memory_channel_rate_limits[itinerary_uuid][channel] = [
        ts for ts in _memory_channel_rate_limits[itinerary_uuid][channel]
        if ts > cutoff
    ]

def check_channel_rate_limit(itinerary_uuid: str, channel: str) -> Tuple[bool, int, int]:
    """Check if itinerary/channel is within rate limit.
    Args:
        itinerary_uuid: Itinerary identifier
        channel: 'email' or 'sms'
    Returns:
        Tuple of (allowed, current_count, limit)
    """
    limit = RATE_LIMIT_CHANNELS.get(channel, 5)
    r = _get_redis()
    if r:
        try:
            key = _make_channel_rate_limit_key(itinerary_uuid, channel)
            now = datetime.utcnow().timestamp()
            one_hour_ago = now - 3600
            r.zremrangebyscore(key, 0, one_hour_ago)
            count = r.zcount(key, one_hour_ago, now)
            allowed = count < limit
            return (allowed, int(count), limit)
        except Exception as e:
            logger.warning(f"[alert_rate_limiter] Redis channel rate limit check failed: {e}")
    # In-memory fallback
    _cleanup_memory_channel_rate_limits(itinerary_uuid, channel)
    count = len(_memory_channel_rate_limits[itinerary_uuid][channel])
    allowed = count < limit
    return (allowed, count, limit)

def increment_channel_rate_limit(itinerary_uuid: str, channel: str) -> None:
    """Increment per-channel rate limit counter for itinerary (record alert sent).
    Args:
        itinerary_uuid: Itinerary identifier
        channel: 'email' or 'sms'
    """
    r = _get_redis()
    if r:
        try:
            key = _make_channel_rate_limit_key(itinerary_uuid, channel)
            now = datetime.utcnow().timestamp()
            r.zadd(key, {str(now): now})
            r.expire(key, 3600)
            logger.debug(f"[alert_rate_limiter] Incremented channel rate limit in Redis: {itinerary_uuid} {channel}")
            return
        except Exception as e:
            logger.warning(f"[alert_rate_limiter] Redis channel rate limit increment failed: {e}")
    # In-memory fallback
    _memory_channel_rate_limits[itinerary_uuid][channel].append(datetime.utcnow())
    logger.debug(f"[alert_rate_limiter] Incremented channel rate limit in memory: {itinerary_uuid} {channel}")

def get_channel_rate_limit_stats(itinerary_uuid: str, channel: str) -> Dict[str, any]:
    """Get detailed rate limit statistics for itinerary/channel.
    Args:
        itinerary_uuid: Itinerary identifier
        channel: 'email' or 'sms'
    Returns:
        Dictionary with rate limit stats
    """
    allowed, current_count, limit = check_channel_rate_limit(itinerary_uuid, channel)
    remaining = max(0, limit - current_count)
    reset_in_seconds = 0
    r = _get_redis()
    if r:
        try:
            key = _make_channel_rate_limit_key(itinerary_uuid, channel)
            oldest = r.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_timestamp = oldest[0][1]
                now = datetime.utcnow().timestamp()
                reset_in_seconds = max(0, int(3600 - (now - oldest_timestamp)))
        except Exception:
            pass
    else:
        if _memory_channel_rate_limits[itinerary_uuid][channel]:
            oldest_ts = min(_memory_channel_rate_limits[itinerary_uuid][channel])
            age = (datetime.utcnow() - oldest_ts).total_seconds()
            reset_in_seconds = max(0, int(3600 - age))
    return {
        'allowed': allowed,
        'current_count': current_count,
        'limit': limit,
        'remaining': remaining,
        'reset_in_seconds': reset_in_seconds
    }
"""alert_rate_limiter.py - Rate limiting and debounce for geofenced alerts.

Multi-tier architecture:
- Redis (preferred): Distributed rate limiting with atomic operations
- In-memory fallback: Process-local counters when Redis unavailable

Rate limits:
- Per-itinerary: Max 5 alerts per hour (prevents spam)
- Debounce: 24-hour TTL on (itinerary_uuid + geofence_id + threat_id) combinations

Design rationale:
- Redis ensures consistency across multiple workers/instances
- TTL-based cleanup (no manual expiry needed)
- Graceful degradation to in-memory when Redis unavailable
- Hash-based deduplication prevents duplicate alerts
"""

from __future__ import annotations
import os
import hashlib
import logging
from typing import Optional, Dict, Set, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# In-memory fallback state (process-local)
_memory_debounce: Set[str] = set()
_memory_rate_limits: Dict[str, list] = defaultdict(list)  # itinerary_uuid -> [timestamps]
_memory_debounce_expiry: Dict[str, datetime] = {}  # debounce_key -> expiry_time

# Configuration

# Per-itinerary global limit (legacy)
RATE_LIMIT_ALERTS_PER_HOUR = 5
DEBOUNCE_TTL_HOURS = 24
REDIS_KEY_PREFIX = "alerts:"

# Per-channel limits (configurable)
RATE_LIMIT_CHANNELS = {
    'email': 10,   # max 10 email alerts/hour/itinerary
    'sms': 3       # max 3 sms alerts/hour/itinerary
}


def _get_redis():
    """Get Redis connection if available."""
    try:
        import redis
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            return None
        r = redis.from_url(redis_url, decode_responses=True, socket_timeout=5)
        r.ping()
        return r
    except ImportError:
        logger.debug("[alert_rate_limiter] redis package not installed")
        return None
    except Exception as e:
        logger.debug("[alert_rate_limiter] Redis unavailable: %s", e)
        return None


def _make_debounce_key(itinerary_uuid: str, geofence_id: str, threat_id: str) -> str:
    """Generate deterministic debounce key.
    
    Hash format: sha256(itinerary_uuid|geofence_id|threat_id)[:16]
    Example: "abc-123|hotel|threat-456" -> "a1b2c3d4e5f6g7h8"
    """
    composite = f"{itinerary_uuid}|{geofence_id}|{threat_id}"
    return hashlib.sha256(composite.encode()).hexdigest()[:16]


def _make_rate_limit_key(itinerary_uuid: str) -> str:
    """Generate Redis key for rate limit counter.
    
    Format: alerts:ratelimit:{itinerary_uuid}
    """
    return f"{REDIS_KEY_PREFIX}ratelimit:{itinerary_uuid}"


def _make_debounce_redis_key(debounce_key: str) -> str:
    """Generate Redis key for debounce hash.
    
    Format: alerts:debounce:{hash}
    """
    return f"{REDIS_KEY_PREFIX}debounce:{debounce_key}"


def _cleanup_memory_debounce():
    """Remove expired debounce entries from in-memory store."""
    now = datetime.utcnow()
    expired = [k for k, exp in _memory_debounce_expiry.items() if exp <= now]
    for k in expired:
        _memory_debounce.discard(k)
        del _memory_debounce_expiry[k]


def _cleanup_memory_rate_limits(itinerary_uuid: str):
    """Remove timestamps older than 1 hour for in-memory rate limits."""
    cutoff = datetime.utcnow() - timedelta(hours=1)
    _memory_rate_limits[itinerary_uuid] = [
        ts for ts in _memory_rate_limits[itinerary_uuid] 
        if ts > cutoff
    ]


def is_alert_debounced(itinerary_uuid: str, geofence_id: str, threat_id: str) -> bool:
    """Check if alert is debounced (already sent within TTL window).
    
    Args:
        itinerary_uuid: Itinerary identifier
        geofence_id: Geofence location identifier
        threat_id: Threat/incident identifier
        
    Returns:
        True if alert should be suppressed (already sent), False if new alert
    """
    debounce_key = _make_debounce_key(itinerary_uuid, geofence_id, threat_id)
    r = _get_redis()
    
    if r:
        # Redis path: check key existence
        try:
            redis_key = _make_debounce_redis_key(debounce_key)
            exists = r.exists(redis_key)
            return bool(exists)
        except Exception as e:
            logger.warning("[alert_rate_limiter] Redis debounce check failed: %s", e)
            # Fall through to memory fallback
    
    # In-memory fallback
    _cleanup_memory_debounce()
    return debounce_key in _memory_debounce


def mark_alert_sent(itinerary_uuid: str, geofence_id: str, threat_id: str) -> None:
    """Mark alert as sent (add to debounce store with TTL).
    
    Args:
        itinerary_uuid: Itinerary identifier
        geofence_id: Geofence location identifier
        threat_id: Threat/incident identifier
    """
    debounce_key = _make_debounce_key(itinerary_uuid, geofence_id, threat_id)
    r = _get_redis()
    
    if r:
        # Redis path: set key with TTL
        try:
            redis_key = _make_debounce_redis_key(debounce_key)
            ttl_seconds = DEBOUNCE_TTL_HOURS * 3600
            r.setex(redis_key, ttl_seconds, "1")
            logger.debug("[alert_rate_limiter] Marked alert sent in Redis: %s (TTL: %dh)", 
                        debounce_key, DEBOUNCE_TTL_HOURS)
            return
        except Exception as e:
            logger.warning("[alert_rate_limiter] Redis mark_alert_sent failed: %s", e)
            # Fall through to memory fallback
    
    # In-memory fallback
    _memory_debounce.add(debounce_key)
    expiry = datetime.utcnow() + timedelta(hours=DEBOUNCE_TTL_HOURS)
    _memory_debounce_expiry[debounce_key] = expiry
    logger.debug("[alert_rate_limiter] Marked alert sent in memory: %s (expires: %s)", 
                debounce_key, expiry.isoformat())


def check_rate_limit(itinerary_uuid: str) -> Tuple[bool, int, int]:
    """Check if itinerary is within rate limit.
    
    Args:
        itinerary_uuid: Itinerary identifier
        
    Returns:
        Tuple of (allowed, current_count, limit)
        - allowed: True if alert can be sent, False if rate limited
        - current_count: Number of alerts sent in last hour
        - limit: Maximum alerts per hour
    """
    r = _get_redis()
    
    if r:
        # Redis path: sorted set with timestamp scores
        try:
            key = _make_rate_limit_key(itinerary_uuid)
            now = datetime.utcnow().timestamp()
            one_hour_ago = now - 3600
            
            # Remove old entries (cleanup)
            r.zremrangebyscore(key, 0, one_hour_ago)
            
            # Count entries in last hour
            count = r.zcount(key, one_hour_ago, now)
            allowed = count < RATE_LIMIT_ALERTS_PER_HOUR
            
            return (allowed, int(count), RATE_LIMIT_ALERTS_PER_HOUR)
        except Exception as e:
            logger.warning("[alert_rate_limiter] Redis rate limit check failed: %s", e)
            # Fall through to memory fallback
    
    # In-memory fallback
    _cleanup_memory_rate_limits(itinerary_uuid)
    count = len(_memory_rate_limits[itinerary_uuid])
    allowed = count < RATE_LIMIT_ALERTS_PER_HOUR
    
    return (allowed, count, RATE_LIMIT_ALERTS_PER_HOUR)


def increment_rate_limit(itinerary_uuid: str) -> None:
    """Increment rate limit counter for itinerary (record alert sent).
    
    Args:
        itinerary_uuid: Itinerary identifier
    """
    r = _get_redis()
    
    if r:
        # Redis path: add timestamp to sorted set
        try:
            key = _make_rate_limit_key(itinerary_uuid)
            now = datetime.utcnow().timestamp()
            
            # Add current timestamp with 1-hour TTL on the key
            r.zadd(key, {str(now): now})
            r.expire(key, 3600)
            
            logger.debug("[alert_rate_limiter] Incremented rate limit in Redis: %s", itinerary_uuid)
            return
        except Exception as e:
            logger.warning("[alert_rate_limiter] Redis rate limit increment failed: %s", e)
            # Fall through to memory fallback
    
    # In-memory fallback
    _memory_rate_limits[itinerary_uuid].append(datetime.utcnow())
    logger.debug("[alert_rate_limiter] Incremented rate limit in memory: %s", itinerary_uuid)


def get_rate_limit_stats(itinerary_uuid: str) -> Dict[str, any]:
    """Get detailed rate limit statistics for itinerary.
    
    Args:
        itinerary_uuid: Itinerary identifier
        
    Returns:
        Dictionary with rate limit stats:
        - allowed: Whether next alert would be allowed
        - current_count: Alerts sent in last hour
        - limit: Maximum alerts per hour
        - remaining: Alerts remaining before rate limit
        - reset_in_seconds: Time until oldest alert expires
    """
    allowed, current_count, limit = check_rate_limit(itinerary_uuid)
    remaining = max(0, limit - current_count)
    
    # Calculate reset time (when oldest alert expires)
    reset_in_seconds = 0
    r = _get_redis()
    
    if r:
        try:
            key = _make_rate_limit_key(itinerary_uuid)
            oldest = r.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_timestamp = oldest[0][1]
                now = datetime.utcnow().timestamp()
                reset_in_seconds = max(0, int(3600 - (now - oldest_timestamp)))
        except Exception:
            pass
    else:
        # In-memory fallback
        if _memory_rate_limits[itinerary_uuid]:
            oldest_ts = min(_memory_rate_limits[itinerary_uuid])
            age = (datetime.utcnow() - oldest_ts).total_seconds()
            reset_in_seconds = max(0, int(3600 - age))
    
    return {
        'allowed': allowed,
        'current_count': current_count,
        'limit': limit,
        'remaining': remaining,
        'reset_in_seconds': reset_in_seconds
    }


def clear_rate_limit(itinerary_uuid: str) -> None:
    """Clear rate limit counter for itinerary (admin/testing use).
    
    Args:
        itinerary_uuid: Itinerary identifier
    """
    r = _get_redis()
    
    if r:
        try:
            key = _make_rate_limit_key(itinerary_uuid)
            r.delete(key)
            logger.info("[alert_rate_limiter] Cleared rate limit in Redis: %s", itinerary_uuid)
        except Exception as e:
            logger.warning("[alert_rate_limiter] Redis clear rate limit failed: %s", e)
    
    # Always clear memory state
    if itinerary_uuid in _memory_rate_limits:
        del _memory_rate_limits[itinerary_uuid]
        logger.info("[alert_rate_limiter] Cleared rate limit in memory: %s", itinerary_uuid)


def clear_all_debounce() -> None:
    """Clear all debounce state (admin/testing use).
    
    Warning: This clears Redis and in-memory debounce stores globally.
    """
    r = _get_redis()
    
    if r:
        try:
            # Scan and delete all debounce keys
            pattern = f"{REDIS_KEY_PREFIX}debounce:*"
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = r.scan(cursor, match=pattern, count=100)
                if keys:
                    r.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            logger.info("[alert_rate_limiter] Cleared %d debounce keys from Redis", deleted)
        except Exception as e:
            logger.warning("[alert_rate_limiter] Redis clear debounce failed: %s", e)
    
    # Clear memory state
    _memory_debounce.clear()
    _memory_debounce_expiry.clear()
    logger.info("[alert_rate_limiter] Cleared in-memory debounce state")


__all__ = [
    'is_alert_debounced',
    'mark_alert_sent',
    'check_rate_limit',
    'increment_rate_limit',
    'get_rate_limit_stats',
    'clear_rate_limit',
    'clear_all_debounce',
    'RATE_LIMIT_ALERTS_PER_HOUR',
    'DEBOUNCE_TTL_HOURS'
]
